from pathlib import Path

import aws_cdk.aws_iam as iam
from aws_cdk import CfnOutput, Stack
from aws_cdk.aws_ecr import LifecycleRule, Repository
from aws_cdk.aws_ecr_assets import DockerImageAsset, Platform
from cdk_ecr_deployment import DockerImageName, ECRDeployment
from constructs import Construct

from typing import Optional, List, Dict

class ECRRepository(Construct):
    ecr_repo: Repository

    def __init__(
            self,
            scope: Construct,
            id: str,
            repository_name: str,
            code_path: Path,
            image_tag: str,
            workload_accounts: List[str] = [],
            function_name_pattern: Optional[str] = None,
            build_args: Optional[Dict] = None,
            **kwargs
    ) -> None:
        super().__init__(scope, id)

        self.ecr_repo = Repository(self, f'{repository_name}Repository',
          repository_name=repository_name,
          image_scan_on_push=True,
          lifecycle_rules=[
              LifecycleRule(
                  rule_priority=1,
                  description="Keep last 10 images",
                  max_image_count=10,
              )
          ]
        )

        read_write_policy = iam.PolicyStatement(
            sid="AllowPushPull",
            effect=iam.Effect.ALLOW,
            principals=[iam.AccountRootPrincipal()],
            actions=[
                "ecr:BatchCheckLayerAvailability",
                "ecr:BatchGetImage",
                "ecr:CompleteLayerUpload",
                "ecr:GetDownloadUrlForLayer",
                "ecr:InitiateLayerUpload",
                "ecr:PutImage",
                "ecr:UploadLayerPart"
            ]
        )
        self.ecr_repo.add_to_resource_policy(read_write_policy)

        if workload_accounts:
            account_policy = iam.PolicyStatement(
                sid="PrivateReadOnly",
                effect=iam.Effect.ALLOW,
                principals=[iam.ArnPrincipal(f"arn:aws:iam::{workload_account}:root") for workload_account in workload_accounts],
                actions=[
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:BatchGetImage",
                    "ecr:DescribeImageScanFindings",
                    "ecr:DescribeImages",
                    "ecr:DescribeRepositories",
                    "ecr:GetAuthorizationToken",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:GetLifecyclePolicy",
                    "ecr:GetLifecyclePolicyPreview",
                    "ecr:GetRepositoryPolicy",
                    "ecr:ListImages",
                    "ecr:ListTagsForResource"
                ]
            )
            self.ecr_repo.add_to_resource_policy(account_policy)

        if function_name_pattern:
            lambda_policy = iam.PolicyStatement(
                sid="LambdaCrossAccountRead",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("lambda.amazonaws.com")],
                actions=[
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:BatchGetImage",
                    "ecr:DescribeImageScanFindings",
                    "ecr:DescribeImages",
                    "ecr:DescribeRepositories",
                    "ecr:GetAuthorizationToken",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:GetLifecyclePolicy",
                    "ecr:GetLifecyclePolicyPreview",
                    "ecr:GetRepositoryPolicy",
                    "ecr:ListImages",
                    "ecr:ListTagsForResource"
                ],
                conditions={
                    "StringLike": {
                        "aws:sourceArn": [f"arn:aws:lambda:{Stack.of(self).region}:{workload_account}:function:{function_name_pattern}" for workload_account in workload_accounts]
                    }
                }
            )
            self.ecr_repo.add_to_resource_policy(lambda_policy)

        image = DockerImageAsset(self, f'{repository_name}DockerImage',
                                 directory=str(code_path),
                                 platform=Platform.LINUX_AMD64,
                                 build_args=build_args
        )

        ECRDeployment(self,
                      f'{repository_name}EcrDeployment',
                      src=DockerImageName(image.image_uri),
                      dest=DockerImageName(f'{self.ecr_repo.repository_uri}:{image_tag}'),
                      )

        ECRDeployment(self,
                      f'{repository_name}EcrDeploymentLatest',
                      src=DockerImageName(image.image_uri),
                      dest=DockerImageName(f'{self.ecr_repo.repository_uri}:latest'),
                      )

        CfnOutput(self, 'ImageUri', value=self.ecr_repo.repository_uri)
        CfnOutput(self, 'ImageTag', value=image_tag)
        CfnOutput(self, 'RepositoryArn', value=self.ecr_repo.repository_arn)
