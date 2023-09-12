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
import os

SERVICE_PORT = 80

class SimpleEC2Service(Construct):
    def __init__(self, scope: Construct, id: str,
                 vpc: ec2.IVpc,
                 associate_public_ip: bool,
                 public_key: str,
                 instance_type: str,
                 max_capacity: int,
                 desired_capacity: int,
                 **kwargs) -> None:
        super().__init__(scope, id)

        self.cluster = ecs.Cluster(self, "Cluster",
                                   vpc=vpc
                                   )

        # Create the launch template
        def read_pub_key(public_key_file: str):
            with open(os.path.expandvars(public_key_file)) as fp:
                pub_key = fp.readlines()[-1]

            return ec2.CfnKeyPair(self, "SSHKey",
                                  key_name=f"{id}EC2InstanceSSHKey",
                                  public_key_material=pub_key)

        key_name = None
        if public_key:
            ssh_key = read_pub_key(public_key)
            key_name = ssh_key.key_name


        # Create an Auto Scaling Group
        security_group=None
        security_group = ec2.SecurityGroup(self, "SG",
                                           vpc=vpc,
                                           allow_all_outbound=True)
        security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(SERVICE_PORT)
        )
        if associate_public_ip:
            subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
            security_group.add_ingress_rule(
                peer=ec2.Peer.any_ipv4(),
                connection=ec2.Port.tcp(22)
            )
        else:
            subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)

        self.auto_scaling_group = autoscaling.AutoScalingGroup(self, "AutoScalingGroup",
                                                          vpc=vpc,
                                                          max_capacity=max_capacity,
                                                          desired_capacity=desired_capacity,
                                                          machine_image=ecs.EcsOptimizedImage.amazon_linux2(),
                                                          instance_type=ec2.InstanceType("t3.small"),
                                                          key_name=key_name,
                                                          security_group=security_group,
                                                          vpc_subnets=subnets)

        # Add custom cluster capacity
        self.capacity_provider = ecs.AsgCapacityProvider(self, "AsgCapacityProvider",
                                                         auto_scaling_group=self.auto_scaling_group
                                                         )
        self.cluster.add_asg_capacity_provider(self.capacity_provider)

        # service

        self.log_group = logs.LogGroup(self, "Logs",
                                       retention=logs.RetentionDays.ONE_WEEK,
                                       removal_policy=cdk.RemovalPolicy.DESTROY)

        task_definition = ecs.Ec2TaskDefinition(self, "TaskDef")
        self.container_name = 'web-example'
        task_definition.add_container(self.container_name,
                                      image=ecs.ContainerImage.from_registry("amazon/amazon-ecs-sample"),
                                      memory_reservation_mib=256,

                                      port_mappings=[ecs.PortMapping(
                                        container_port=SERVICE_PORT,
                                        host_port=SERVICE_PORT,
                                        name=f"web-example-port",
                                        protocol=ecs.Protocol.TCP
                                        )],
                                      logging=ecs.LogDrivers.aws_logs(
                                          log_group=self.log_group,
                                          stream_prefix="ecs"
                                      ))
        self.service_port = SERVICE_PORT
        self.service = ecs.Ec2Service(self, "EC2Service",
                       cluster=self.cluster,
                       task_definition=task_definition,
                       capacity_provider_strategies=[ecs.CapacityProviderStrategy(
                           capacity_provider=self.capacity_provider.capacity_provider_name,
                           weight=1
                       )])

        CfnOutput(self, f"{id}CapacityProviderName", value=self.capacity_provider.capacity_provider_name)
        CfnOutput(self, f"{id}ClusterName", value=self.cluster.cluster_name)