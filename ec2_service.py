import aws_cdk as cdk
from aws_cdk import CfnOutput, Environment
from constructs import Construct

from aws_cdk import (
    aws_iam as iam,
    aws_logs as logs,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_autoscaling as autoscaling
)

import re
import os
from pathlib import Path

from typing import Optional, Sequence, Mapping, Union, Dict

class EC2Cluster(Construct):
    def __init__(self, scope: Construct, id: str,
                 vpc: ec2.IVpc,
                 subnets: ec2.SubnetSelection,
                 user_data_path: Optional[str],
                 public_key: str,
                 instance_type: str,
                 env_dict: dict,
                 max_capacity: int,
                 desired_capacity: int,
                 **kwargs) -> None:
        super().__init__(scope, id)

        self.cluster = ecs.Cluster(self, "Cluster",
            vpc=vpc
        )

        # IAM role for to add bucket permissions
        self.iam_role = iam.Role(self, "Role",
                                  assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
                                  description="")

        # Customized capacity for cluster

        # user data for launch template
        user_data = ec2.UserData.for_linux()

        for k,v in env_dict.items():
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
        def read_pub_key(public_key_file: str):
            with open(os.path.expandvars(public_key_file)) as fp:
                pub_key = fp.readlines()[-1]

            return ec2.CfnKeyPair(self, "SSHKey",
                                     key_name=f"{id}EC2InstanceSSHKey",
                                     public_key_material=pub_key)
        key_name=None
        if public_key:
            ssh_key = read_pub_key(public_key)
            key_name = ssh_key.key_name

        launch_template = ec2.LaunchTemplate(self, "LaunchTemplate",
            machine_image=ecs.EcsOptimizedImage.amazon_linux2(),
            user_data=user_data,
            role=self.iam_role,
            instance_type=ec2.InstanceType(instance_type),
            key_name=key_name,
            security_group=self.security_group,
        )

        # Create an Auto Scaling Group
        auto_scaling_group = autoscaling.AutoScalingGroup(self, "AutoScalingGroup",
            vpc=vpc,
            max_capacity=max_capacity,
            desired_capacity=desired_capacity,
            launch_template=launch_template,
            vpc_subnets=subnets
        )

        # Add custom cluster capacity
        self.capacity_provider = ecs.AsgCapacityProvider(self, "AsgCapacityProvider",
            auto_scaling_group=auto_scaling_group
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
                 ports: Optional[Sequence[int]] = None,
                 container_environment: Optional[Mapping[str, str]] = None,
                 command: Optional[Sequence[str]] = None,
                 secrets: Optional[Mapping[str, ecs.Secret]] = None,
                 **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        self.log_group = logs.LogGroup(self, "Logs",
                                       retention=logs.RetentionDays.ONE_WEEK,
                                       removal_policy=cdk.RemovalPolicy.DESTROY)

        self.task_role = iam.Role(self, "TaskRole",
                             role_name=f"{id}TaskRole",
                             assumed_by=iam.CompositePrincipal(
                                 iam.ServicePrincipal("ecs.amazonaws.com"),
                                 iam.ServicePrincipal("ecs-tasks.amazonaws.com")
                             ))

        # camel to hyphenated case
        _id = re.sub(r'(?<!^)(?=[A-Z])', '-', id).lower()
        task_def_id = task_family_name if task_family_name else _id
        self.task_definition = ecs.Ec2TaskDefinition(self, "TaskDefinition",
                                                  family=task_def_id,
                                                  task_role=self.task_role)

        port_mappings = list()
        for i,port in enumerate(ports):
            port_mappings.append(
                ecs.PortMapping(
                    container_port=port,
                    host_port=port,
                    name=f"{_id}_port{i}",
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

