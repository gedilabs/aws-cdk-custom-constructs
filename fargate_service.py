import aws_cdk as cdk
from aws_cdk import CfnOutput, Environment
from constructs import Construct

from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr

import re
import os

from typing import Optional, Sequence, Mapping, Union

class FargateService(Construct):
    def __init__(self, scope: Construct, id: str,
                 vpc: ec2.IVpc,
                 subnets: ec2.SubnetSelection,
                 cluster: ecs.Cluster,
                 repository: ecr.Repository,
                 image_tag: str,
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

        # camel to hyphenated case
        _id = re.sub(r'(?<!^)(?=[A-Z])', '-', id).lower()
        task_def_id = task_family_name if task_family_name else _id
        self.task_definition = ecs.TaskDefinition(self, "TaskDefinition",
                                                  family=task_def_id,
                                                  compatibility=ecs.Compatibility.EC2_AND_FARGATE,
                                                  cpu=task_cpu,
                                                  memory_mib=task_memory_mib,)

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
        
        self.container_image = ecs.ContainerImage.from_ecr_repository(repository, tag=image_tag) 

        self.container = self.task_definition.add_container(id=id,
                                                            image=self.container_image,
                                                            port_mappings=[port_mapping],
                                                            environment=container_environment,
                                                            essential=True,
                                                            logging=ecs.LogDrivers.aws_logs(
                                                                log_group=self.log_group,
                                                                stream_prefix="ecs"
                                                            ),
                                                            command=command,
                                                            secrets=secrets)

        self.service = ecs.FargateService(self, "Service",
                                          cluster=cluster,
                                          service_name=id,
                                          task_definition=self.task_definition,
                                          security_groups=[self.security_group],
                                          vpc_subnets=subnets,
                                          assign_public_ip=True,
                                          desired_count=container_count)

        CfnOutput(self, 'ServiceTaskDefinition', value=self.service.task_definition.task_definition_arn)
        CfnOutput(self, 'ServiceLogs', value=self.log_group.log_group_arn)

