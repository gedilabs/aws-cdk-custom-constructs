import aws_cdk as cdk
from aws_cdk import CfnOutput, Environment
from constructs import Construct

from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ec2 as ec2

import re
import os

from typing import Optional, Sequence, Mapping, Union

class ECSService(Construct):
    def __init__(self, scope: Construct, id: str,
                 vpc: ec2.IVpc,
                 subnets: ec2.SubnetSelection,
                 cluster: ecs.Cluster,
                 container_image: ecs.ContainerImage,
                 container_count: int = 1,
                 task_family_name: Union[str, None] = None,
                 task_cpu: str = "1024",
                 task_memory_mib: str = "2048",
                 port: Optional[int] = None,
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
        self.task_definition = ecs.TaskDefinition(self, "TaskDefinition",
                                                  family=task_def_id,
                                                  compatibility=ecs.Compatibility.EC2,
                                                  task_role=self.task_role)

        port_mapping = ecs.PortMapping(
            container_port=port,
            host_port=port,
            name=_id,
            protocol=ecs.Protocol.TCP
        ) if port else None

        self.security_group = ec2.SecurityGroup(self, "SecurityGroup",
                                                vpc=vpc,
                                                allow_all_outbound=True
                                                )

        self.container = self.task_definition.add_container(id=id,
                                                            image=container_image,
                                                            port_mappings=[port_mapping],
                                                            environment=container_environment,
                                                            essential=True,
                                                            logging=ecs.LogDrivers.aws_logs(
                                                                log_group=self.log_group,
                                                                stream_prefix="ecs"
                                                            ),
                                                            command=command,
                                                            secrets=secrets)

        #service_connect_config = ecs.ServiceConnectProps(
        #    services=[
        #        ecs.ServiceConnectService(
        #            port_mapping_name=port_mapping.name,
        #            dns_name=port_mapping.name,
        #        )
        #    ]
        #)

        self.service = ecs.FargateService(self, "Service",
                                          cluster=cluster,
                                          service_name=id,
                                          task_definition=self.task_definition,
                                          security_groups=[self.security_group],
                                          vpc_subnets=subnets,
                                          desired_count=container_count,
                                          service_connect_configuration=service_connect_config)

        CfnOutput(self, 'ServiceTaskDefinition', value=self.service.task_definition.task_definition_arn)
        CfnOutput(self, 'ServiceLogs', value=self.log_group.log_group_arn)

