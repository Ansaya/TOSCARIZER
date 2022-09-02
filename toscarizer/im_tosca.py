import yaml
import copy
import random
import string

from toscarizer.utils import RESOURCES_FILE

TOSCA_TEMPLATE = "templates/oscar.yaml"
WN_TOSCA_TEMPLATE = "templates/oscar_wn.yaml"

def get_random_string(length):
    # choose from all lowercase letter
    letters = string.ascii_lowercase
    result_str = ''.join(random.choice(letters) for i in range(length))
    return result_str

def gen_oscar_name():
    # TODO: https://github.com/grycap/im-dashboard/blob/master/app/utils.py#L435
    return "oscar-cluster-%s" % get_random_string(8)


def merge_templates(template, new_template):
    for item in ["inputs", "node_templates", "outputs"]:
        if item in new_template["topology_template"]:
            if item not in template["topology_template"]:
                template["topology_template"][item] = {}
            template["topology_template"][item].update(new_template["topology_template"][item])
    return template


def find_compute_layer(resources, component):
    layer_num = component.get("executionLayer")
    if not layer_num:
        layer_num = component["candidateExecutionLayers"][0]
    for nd in list(resources["System"]["NetworkDomains"].values()):
        if "ComputationalLayers" in nd:
            for _, cl in nd["ComputationalLayers"].items():
                if cl.get("number") == layer_num:
                    return cl
    return None


def find_resource_by_name(compute_layer, cont):
    res_name = cont.get("selectedExecutionResource")
    if not res_name:
        res_name = cont["candidateExecutionResources"][0]
    for res in list(compute_layer["Resources"].values()):
        if res.get("name") == res_name:
            return res
    return None


def add_nets(tosca_tpl):
    tosca_tpl["topology_template"]["node_templates"]["pub_network"] = {"type": "tosca.nodes.network.Network",
                                                                       "properties": {"network_type": "public"}}

    tosca_tpl["topology_template"]["node_templates"]["priv_network"] = {"type": "tosca.nodes.network.Network",
                                                                        "properties": {"network_type": "private"}}
    return tosca_tpl


def set_ip_details(tosca_tpl, node_name, node_net, ip, order):
    port_name = "%s_%s_port" % (node_name, node_net)
    tosca_tpl["topology_template"]["node_templates"][port_name] = {"type": "tosca.nodes.network.Port",
                                                                   "properties": {
                                                                       "order": order,
                                                                       "ip_address": ip
                                                                   },
                                                                   "requirements": [
                                                                       {"binding": node_name},
                                                                       {"link": node_net}
                                                                   ]}
    return tosca_tpl


def set_node_credentials(node_tpl, username, key):
    node_tpl["capabilities"]["os"]["properties"]["credential"] = {"user": username,
                                                                  "token_type": "private_key",
                                                                  "token": key}


def get_physical_resource_data(comp_layer, res, phys_file, node_type, value, index=None):
    for cl in list(phys_file["ComputationalLayers"].values()):
        if cl["number"] == comp_layer["number"]:
            for r in list(cl["Resources"].values()):
                if r["name"] == res["name"]:
                    if index is not None:
                        return r[node_type][index][value]
                    else:
                        return r[node_type][value]
    return None


def gen_tosca_yamls(resource_file, deployments_file, phys_file):
    with open(TOSCA_TEMPLATE, 'r') as f:
        tosca_tpl = yaml.safe_load(f)

    with open(WN_TOSCA_TEMPLATE, 'r') as f:
        wn_tosca_tpl = yaml.safe_load(f)

    tosca_res = {}
    phys_nodes = {}
    res = None
    try:
        with open(resource_file, 'r') as f:
            resources = yaml.safe_load(f)
        with open(deployments_file, 'r') as f:
            deployments = yaml.safe_load(f)

        if "System" in deployments:
            deployments = deployments["System"]

        if phys_file:
            with open(phys_file, 'r') as f:
                phys_nodes = yaml.safe_load(f)

        for _, component in deployments["Components"].items():
            tosca_comp = copy.deepcopy(tosca_tpl)
            compute_layer = find_compute_layer(resources, component)
            if not compute_layer:
                raise Exception("No compute layer found for component." % component.get("name"))

            if compute_layer["type"] != "NativeCloudFunction":
                tosca_comp["topology_template"]["inputs"]["cluster_name"]["default"] = gen_oscar_name()
                tosca_comp["topology_template"]["inputs"]["domain_name"]["default"] = "im.grycap.net"
                tosca_comp["topology_template"]["inputs"]["admin_token"]["default"] = get_random_string(16)
                tosca_comp["topology_template"]["inputs"]["oscar_password"]["default"] = get_random_string(16)
                tosca_comp["topology_template"]["inputs"]["minio_password"]["default"] = get_random_string(16)
                tosca_comp["topology_template"]["inputs"]["fe_os_image"]["default"] = None
                for cont_id, cont in component["Containers"].items():
                    res = find_resource_by_name(compute_layer, cont)
                    if not res:
                        raise Exception("Not resource found for a container in component %s." % component.get("name"))
                    tosca_wn = copy.deepcopy(wn_tosca_tpl)
                    wn_name = "%s_%s" % (component["name"], cont_id)

                    wn_node = tosca_wn["topology_template"]["node_templates"].pop("wn_node")
                    wn_node["requirements"][0]["host"] = "wn_%s" % wn_name

                    wn = tosca_wn["topology_template"]["node_templates"].pop("wn")
                    wn["capabilities"]["scalable"]["properties"]["count"] = res.get("totalNodes")
                    wn["capabilities"]["host"]["properties"]["mem_size"] = "%s MB" % res.get("memorySize")
                    wn["capabilities"]["host"]["properties"]["preemtible_instance"] = res.get("onSpot", False)

                    wn["capabilities"]["os"]["properties"]["distribution"] = res.get("operatingSystemDistribution")
                    wn["capabilities"]["os"]["properties"]["version"] = res.get("operatingSystemVersion")
                    wn["capabilities"]["os"]["properties"]["image"] = res.get("operatingSystemImageId")

                    # For the FE set the image of the first WN
                    if tosca_comp["topology_template"]["inputs"]["fe_os_image"]["default"] is None:
                        tosca_comp["topology_template"]["inputs"]["fe_os_image"]["default"] = res.get("operatingSystemImageId")

                    cores = 0
                    sgx = False
                    for proc in list(res["processors"].values()):
                        cores += proc.get("computingUnits", 0)
                        if proc.get("SGXFlag"):
                            sgx = True

                    gpus = 0
                    gpu_arch = None
                    for acc in list(res.get("accelerators", {}).values()):
                        for proc in list(acc["processors"].values()):
                            if proc.get("type") == "GPU":
                                gpus += proc.get("computingUnits", 0)
                                gpu_arch = proc.get("architecture")


                    wn["capabilities"]["host"]["properties"]["num_cpus"] = cores
                    wn["capabilities"]["host"]["properties"]["sgx"] = sgx
                    if gpus:
                        wn["capabilities"]["host"]["properties"]["num_gpus"] = gpus
                        if gpu_arch:
                            # We asume this format: gpu_model = vendor model
                            gpu_arch_parts = gpu_arch.split()
                            if len(gpu_arch_parts) != 2:
                                raise Exception("GPU architecture must be with format: VENDOR MODEL")
                            wn["capabilities"]["host"]["properties"]["gpu_vendor"] = gpu_arch_parts[0]
                            wn["capabilities"]["host"]["properties"]["gpu_model"] = gpu_arch_parts[1]

                    if compute_layer["type"] == "PhysicalAlreadyProvisioned":
                        # as each wn will have different ip, we have to create 
                        # one node per wn to reach totalNodes
                        wn["capabilities"]["scalable"]["properties"]["count"] = 1
                        for num in range(0, res.get("totalNodes")):
                            ssh_user = get_physical_resource_data(compute_layer, res, phys_nodes, "wns", "ssh_user", num)
                            ssh_key = get_physical_resource_data(compute_layer, res, phys_nodes, "wns", "ssh_key", num)
                            set_node_credentials(wn, ssh_user, ssh_key)

                            wn_ip = get_physical_resource_data(compute_layer, res, phys_nodes, "wns", "private_ip", num)
                            tosca_comp = set_ip_details(tosca_comp, "wn_%s_%s" % (wn_name, num+1), "priv_network", wn_ip, 0)
                            tosca_wn["topology_template"]["node_templates"]["wn_node_%s_%s" % (wn_name, num+1)] = copy.deepcopy(wn_node)
                            tosca_wn["topology_template"]["node_templates"]["wn_%s_%s" % (wn_name, num+1)] = copy.deepcopy(wn)
                            tosca_res[component["name"]] = merge_templates(tosca_comp, tosca_wn)
                    else:
                        tosca_wn["topology_template"]["node_templates"]["wn_node_%s" % wn_name] = wn_node
                        tosca_wn["topology_template"]["node_templates"]["wn_%s" % wn_name] = wn

                        tosca_res[component["name"]] = merge_templates(tosca_comp, tosca_wn)

            if compute_layer["type"] == "PhysicalAlreadyProvisioned":
                if not phys_nodes:
                    raise Exception("Computational layer of type PhysicalAlreadyProvisioned, but Physical Data File not exists.")
                # Add nets to enable to set IP of the nodes
                tosca_comp = add_nets(tosca_comp)
                pub_ip = get_physical_resource_data(compute_layer, res, phys_nodes, "fe_node", "public_ip")
                priv_ip = get_physical_resource_data(compute_layer, res, phys_nodes, "fe_node", "private_ip")
                tosca_comp = set_ip_details(tosca_comp, "front", "pub_network", pub_ip, 1)
                tosca_comp = set_ip_details(tosca_comp, "front", "priv_network", priv_ip, 0)
                ssh_user = get_physical_resource_data(compute_layer, res, phys_nodes, "fe_node", "ssh_user")
                ssh_key = get_physical_resource_data(compute_layer, res, phys_nodes, "fe_node", "ssh_key")
                set_node_credentials(tosca_comp["topology_template"]["node_templates"]["front"], ssh_user, ssh_key)

    except Exception as ex:
        print("Error reading resources file: %s" % ex)

    return tosca_res
