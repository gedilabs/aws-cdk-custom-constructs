import aws_cdk as cdk
from aws_cdk import(
  CfnOutput,
  aws_ec2 as ec2,
  aws_iam as iam,
  aws_ecs as ecs
)
from constructs import Construct
from pathlib import Path
import os

class EC2Instance(Construct):
    def __init__(self, scope: Construct, id: str,
                 vpc: ec2.IVpc,
                 subnets: ec2.SubnetSelection,
                 user_data_path: str,
                 public_key: str,
                 env_dict: dict,
                 **kwargs) -> None:
        super().__init__(scope, id)

        self.iam_role = iam.Role(self, "Role",
                                  assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
                                  description=""
                                  )

        security_group = ec2.SecurityGroup(self, "SG",
                                            vpc=vpc,
                                            allow_all_outbound=True)

        for pn in [22, 80, 443]:
            security_group.add_ingress_rule(
                peer=ec2.Peer.any_ipv4(),
                connection=ec2.Port.tcp(pn)
            )

        with open(os.path.expandvars(public_key)) as fp: 
            pub_key = fp.readlines()[-1]

        ssh_key = ec2.CfnKeyPair(self, "SSHKey",
                                 key_name=f"{id}EC2InstanceSSHKey",
                                 public_key_material=pub_key)

        user_data = ec2.UserData.for_linux()

        print("adding environment user data")
        for k,v in env_dict.items():
            commands = list() 
            commands.append(f"{k}={v}")
            commands.append(f"echo 'export {k}={v}' >> /etc/profile")
            for cmd in commands:
                print(cmd)
                user_data.add_commands(cmd)

        with open(str(user_data_path)) as fp:
            lines = fp.readlines()
            for line in lines:
                user_data.add_commands(line)

        instance = ec2.Instance(self, "EC2",
                              vpc=vpc,
                              vpc_subnets=subnets,
                              role=self.iam_role,
                              security_group=security_group,
                              key_name=ssh_key.key_name,
                              machine_image=ecs.EcsOptimizedImage.amazon_linux(),
                              instance_type=ec2.InstanceType("t2.micro"),
                              user_data=user_data,
                              user_data_causes_replacement=True)

        CfnOutput(self, "EC2InstanceSSHKeyID", value=ssh_key.attr_key_pair_id)
        CfnOutput(self, "EC2InstanceInstanceID", value=instance.instance_id)
        CfnOutput(self, "EC2InstancePublicIP", value=instance.instance_public_ip)
        CfnOutput(self, "EC2InstancePublicDNS", value=instance.instance_public_dns_name)
