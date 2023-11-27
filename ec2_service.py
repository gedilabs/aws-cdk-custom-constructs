import aws_cdk as cdk
from aws_cdk import CfnOutput, Environment
from constructs import Construct

from aws_cdk import (
    aws_iam as iam,
    aws_logs as logs,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_autoscaling as autoscaling,
    custom_resources as cr
)

import re
import os
from pathlib import Path

from typing import Optional, Sequence, Mapping, Union, Dict, List
import logging


class EC2Cluster(Construct):
    def __init__(self, scope: Construct, id: str,
                 vpc: ec2.IVpc,
                 subnets: ec2.SubnetSelection,
                 public_key: str,
                 instance_type: str,
                 env_dict: dict,
                 max_capacity: int,
                 desired_capacity: int,
                 user_data_path: Optional[str] = "",
                 profile_policies: Optional[List[iam.PolicyStatement]] = [],
                 suffix: Optional[str] = "",
                 **kwargs) -> None:
        super().__init__(scope, id)

        self.cluster = ecs.Cluster(self, "Cluster",
                                   vpc=vpc
                                   )

        self.iam_role = iam.Role(self, "Role",
                                 assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
                                 description="")
        for role_policy in profile_policies:
            self.iam_role.add_to_policy(role_policy)

        #        instance_profile = iam.InstanceProfile(self, "InstanceProfile",
        #                            instance_profile_name=f"{id}{suffix}InstanceProfile",
        #                            role=self.iam_role)

        # Customized capacity for cluster

        # user data for launch template
        user_data = ec2.UserData.for_linux()

        for k, v in env_dict.items():
            commands = list()
            commands.append(f"{k}={v}")
            commands.append(f"echo 'export {k}={v}' >> /etc/profile")
            for cmd in commands:
                user_data.add_commands(cmd)

        if user_data_path:
            with open(str(user_data_path)) as fp:
                lines = fp.readlines()
                for line in lines:
                    user_data.add_commands(line)

        self.security_group = ec2.SecurityGroup(self, "SG",
                                                vpc=vpc,
                                                allow_all_outbound=True)

        # Create the launch template
        def read_pub_key(public_key: str):
            if Path(public_key).exists():
                with open(os.path.expandvars(public_key)) as fp:
                    pk = fp.readlines()[-1].strip()
                    print(f"Public key from file :: {pk}")
            else:
                pk = public_key.strip()
                print(f"Public key from string :: {pk}")

            return ec2.CfnKeyPair(self, "SSHKey",
                                  key_name=f"{id}EC2InstanceSSHKey",
                                  public_key_material=pk)

        key_name = None
        if public_key:
            ssh_key = read_pub_key(public_key)
            key_name = ssh_key.key_name

        launch_template = ec2.LaunchTemplate(self, "LaunchTemplate",
                                             machine_image=ecs.EcsOptimizedImage.amazon_linux2(),
                                             user_data=user_data,
                                             role=self.iam_role,
                                             # instance_profile=instance_profile,
                                             instance_type=ec2.InstanceType(instance_type),
                                             key_name=key_name,
                                             security_group=self.security_group,
                                             )

        # Create an Auto Scaling Group
        self.auto_scaling_group = autoscaling.AutoScalingGroup(self, "AutoScalingGroup",
                                                               vpc=vpc,
                                                               max_capacity=max_capacity,
                                                               desired_capacity=desired_capacity,
                                                               launch_template=launch_template,
                                                               vpc_subnets=subnets
                                                               )

        # for ASG deletions: https://github.com/aws/aws-cdk/issues/18179
        asg_force_delete = cr.AwsCustomResource(self, "AsgForceDelete",
                                                on_delete=cr.AwsSdkCall(
                                                    service='AutoScaling',
                                                    action='deleteAutoScalingGroup',
                                                    parameters={
                                                        "AutoScalingGroupName": self.auto_scaling_group.auto_scaling_group_name,
                                                        "ForceDelete": True
                                                    }
                                                ),
                                                policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                                                    resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
                                                )
                                                )
        asg_force_delete.node.add_dependency(self.auto_scaling_group)

        # Add custom cluster capacity
        self.capacity_provider = ecs.AsgCapacityProvider(self, "AsgCapacityProvider",
                                                         auto_scaling_group=self.auto_scaling_group
                                                         )
        self.cluster.add_asg_capacity_provider(self.capacity_provider)


class EC2Service(Construct):
    def __init__(self, scope: Construct, id: str,
                 vpc: ec2.IVpc,
                 subnets: ec2.SubnetSelection,
                 ec2_cluster: EC2Cluster,
                 container_image: ecs.ContainerImage,
                 container_name: str,
                 task_family_name: Union[str, None] = None,
                 task_cpu: int = 1024,
                 task_memory_mib: int = 256,
                 repository: Optional[ecr.IRepository] = None,
                 ports: Optional[Sequence[int]] = None,
                 container_environment: Optional[Mapping[str, str]] = None,
                 command: Optional[Sequence[str]] = None,
                 task_role: Optional[iam.IRole] = None,
                 secret_arn: Optional[str] = None,
                 secrets: Optional[Mapping[str, ecs.Secret]] = None,
                 suffix: Optional[str] = "",
                 **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        self.log_group = logs.LogGroup(self, "Logs",
                                       retention=logs.RetentionDays.ONE_WEEK,
                                       removal_policy=cdk.RemovalPolicy.DESTROY)

        policy_document = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    effect=iam.Effect.ALLOW,
                    resources=[
                        self.log_group.log_group_arn,
                        f"{self.log_group.log_group_arn}:log-stream:ecs/{id}*"
                    ],
                    sid="AllowStreamingLogsToCloudWatch"
                )
            ]
        )

        if repository:
            policy_document.add_statements(
                iam.PolicyStatement(
                    actions=["ecr:GetAuthorizationToken"],
                    effect=iam.Effect.ALLOW,
                    resources=["*"],
                    sid="AllowGettingECRAuthorizationToken"
                ),
                iam.PolicyStatement(
                    actions=[
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:BatchGetImage",
                        "ecr:GetDownloadUrlForLayer"
                    ],
                    effect=iam.Effect.ALLOW,
                    resources=[repository.repository_arn],
                    sid="AllowReadingFromECR"
                )
            )

        if secret_arn:
            policy_document.add_statements(
                iam.PolicyStatement(
                    actions=[
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:GetResourcePolicy",
                        "secretsmanager:GetSecretValue",
                        "secretsmanager:ListSecretVersionIds"
                    ],
                    effect=iam.Effect.ALLOW,
                    resources=[
                        secret_arn
                    ],
                    sid="AllowReadingSecret"
                )
            )

        self.task_execution_role = iam.Role(self, f"{id}TaskExecutionRole",
                                            assumed_by=iam.CompositePrincipal(
                                                iam.ServicePrincipal("ecs.amazonaws.com"),
                                                iam.ServicePrincipal("ecs-tasks.amazonaws.com")
                                            ),
                                            inline_policies={
                                                f"{id}-task-execution-policy": policy_document
                                            })

        # camel to hyphenated case
        camel_case_id = re.sub(r'(?<!^)(?=[A-Z])', '-', id).lower()
        task_def_id = task_family_name if task_family_name else camel_case_id
        self.task_definition = ecs.Ec2TaskDefinition(self, "TaskDefinition",
                                                     family=task_def_id,
                                                     task_role=task_role,
                                                     execution_role=self.task_execution_role)

        port_mappings = list()
        for i, port in enumerate(ports):
            port_mappings.append(
                ecs.PortMapping(
                    container_port=port,
                    host_port=port,
                    name=f"{camel_case_id}_port{i}",
                    protocol=ecs.Protocol.TCP
                )
            )

        port_mappings = port_mappings if ports else None
        self.container_name = container_name
        self.container = self.task_definition.add_container(id=self.container_name,
                                                            image=container_image,
                                                            port_mappings=port_mappings,
                                                            environment=container_environment,
                                                            memory_reservation_mib=task_memory_mib,
                                                            logging=ecs.LogDrivers.aws_logs(
                                                                log_group=self.log_group,
                                                                stream_prefix="ecs"
                                                            ),
                                                            command=command,
                                                            secrets=secrets)

        self.service = ecs.Ec2Service(self, "Service",
                                      cluster=ec2_cluster.cluster,
                                      service_name=id,
                                      task_definition=self.task_definition,
                                      capacity_provider_strategies=[ecs.CapacityProviderStrategy(
                                          capacity_provider=ec2_cluster.capacity_provider.capacity_provider_name,
                                          weight=1)])

        CfnOutput(self, 'ServiceTaskDefinition', value=self.service.task_definition.task_definition_arn)
        CfnOutput(self, 'ServiceLogs', value=self.log_group.log_group_arn)
