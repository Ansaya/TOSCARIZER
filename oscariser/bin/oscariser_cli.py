import click
import yaml
import sys

sys.path.append(".")

from oscariser.utils import parse_dag, parse_resources, RESOURCES_FILE, DAG_FILE
from oscariser.fdl import generate_fdl
from oscariser.docker_images import generate_dockerfiles, build_and_push, update_resources
from oscariser.im_tosca import gen_tosca_yaml


@click.group()
def oscariser_cli():
    pass


@click.command()
@click.option("--design-dir", help="Path to the design of the AI-SPRINT application.", type=str, required=True)
@click.option("--username", help="Username to login to the docker registry.", type=str, required=True)
@click.option("--password", help="Pasword to login to the docker registry.", type=str, required=True)
@click.option("--registry", help="Registry to push the generated docker images.", type=str, required=True)
@click.option("--dry-run", help="Registry to push the generated docker images.", default=False, is_flag=True)
def docker(design_dir, username, password, registry, dry_run):
    resources = parse_resources("%s/%s" % (design_dir, RESOURCES_FILE))
    dag = parse_dag("%s/%s" % (design_dir, DAG_FILE))
    dockerfiles = generate_dockerfiles(dag, resources)
    docker_images = build_and_push(registry, dockerfiles, username, password, None, not dry_run, not dry_run)
    print("Docker images generated and pushed to the registry.")
    print("\n".join(map(lambda x: "%s: %s" % (x, docker_images[x][1]), docker_images)))
    update_resources(docker_images, "%s/%s" % (design_dir, RESOURCES_FILE))
    print("DONE. Updated resouces file with new image links.")


@click.command()
@click.option("--design-dir", help="Path to the design of the AI-SPRINT application.", type=str, required=True)
def fdl(design_dir):
    resources = parse_resources("%s/%s" % (design_dir, RESOURCES_FILE))
    dag = parse_dag("%s/%s" % (design_dir, DAG_FILE))
    fdl = generate_fdl(dag, resources)
    fdl_file = "%s/oscar/fdl.yaml" % design_dir
    with open(fdl_file, 'w+') as f:
        yaml.safe_dump(fdl, f, indent=2)
    print("DONE. FDL file %s has been generated." % fdl_file)


@click.command()
@click.option("--design-dir", help="Path to the design of the AI-SPRINT application.", type=str, required=True)
def tosca(design_dir):
    toscas = gen_tosca_yaml("%s/%s" % (design_dir, RESOURCES_FILE))
    for cl, tosca in toscas.items():
        tosca_file = "%s/im/%s.yaml" % (design_dir, cl)
        with open(tosca_file, 'w+') as f:
            yaml.safe_dump(tosca, f, indent=2)
        print("DONE. TOSCA file %s has been generated for Computational Layer: %s." % (tosca_file, cl))


oscariser_cli.add_command(docker)
oscariser_cli.add_command(fdl)
oscariser_cli.add_command(tosca)

if __name__ == '__main__':
    oscariser_cli()
