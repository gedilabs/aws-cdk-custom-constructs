import aws_cdk as cdk
from aws_cdk import CfnOutput, Environment
from constructs import Construct
from aws_cdk.aws_ecr import LifecycleRule, Repository
from aws_cdk.aws_ecr_assets import DockerImageAsset, Platform
from cdk_ecr_deployment import DockerImageName, ECRDeployment

from pathlib import Path
from aws_cdk import aws_iam as iam
class ECRRepository(Construct):
    def __init__(
            self, scope: Construct, id: str,
            repository_name: str,
            code_path: Path,
            image_tag: str) -> None:
        super().__init__(scope, id)

        self.ecr_repo = Repository(self,
                                   f'{repository_name}Repository',
                                   repository_name=repository_name,
                                   image_scan_on_push=True,
                                   auto_delete_images=True,
                                   removal_policy=cdk.RemovalPolicy.DESTROY,
                                   lifecycle_rules=[
                                       LifecycleRule(
                                           rule_priority=1,
                                           description="Keep last 10 docker",
                                           max_image_count=10,
                                       )
                                   ])
        image = DockerImageAsset(self,
            'DockerImage',
            directory=str(code_path),
            platform=Platform.LINUX_AMD64)

        ECRDeployment(self,
                      f'{repository_name}EcrDeployment',
                      src=DockerImageName(image.image_uri),
                      dest=DockerImageName(f'{self.ecr_repo.repository_uri}:{image_tag}')
                      )

        CfnOutput(self, 'ImageUri', value=self.ecr_repo.repository_uri)
        CfnOutput(self, 'ImageTag', value=image_tag)
        CfnOutput(self, 'RepositoryArn', value=self.ecr_repo.repository_arn)
