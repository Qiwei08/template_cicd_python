import logging

from saagieapi import SaagieApi, GraphPipeline, ConditionNode, JobNode, ConditionStatusNode, ConditionExpressionNode
import json
import shutil
import os
import yaml
from pathlib import Path


def handle_log_error(msg, exception):
    logging.warning(msg)
    logging.error("Something went wrong %s", exception)
    raise exception


def package_code(name_file, root_dir, archive_format="zip"):
    """
    Create a zip archive of a directory
    :param name_file: string, name of the file to create, including the path, minus any format-specific extension
    :param root_dir: string, a directory that will be the root directory of the archive
    :param archive_format: string, archive format, can be "zip", "tar", "gztar", "bztar" or "bztar"
    :return: string, name of the archive
    """
    if root_dir:
        return shutil.make_archive(name_file, archive_format, root_dir)
    else:
        return None


def connect_to_saagie(url, id_platform, user, password, realm):
    """
    Create an instance of SaagieAPI in order to interact with Saagie
    :param url: string, Saagie URL
    :param id_platform: string, Saagie ID platform
    :param user: string, Saagie's user
    :param password: string, Saagie user's password
    :param realm: string, Saagie realm
    :return: instance of SaagieAPI
    """
    logging.debug(f"Connecting to Saagie ...")
    saagie_client = SaagieApi(url_saagie=url,
                              id_platform=id_platform,
                              user=user,
                              password=password,
                              realm=realm)

    return saagie_client


def create_or_upgrade_job(client_saagie, job_config_file, env):
    """
    Package code and then create or upgrade a job on Saagie
    :param client_saagie: SaagieAPI, an instance of SaagieAPI
    :param job_config_file: str, job config file path
    :param env: str, environment of Saagie that you want to create or upgrade job
    :return: dict, dict of job informaiton
    """
    try:
        logging.debug(f"Loading job config file: [{job_config_file}] ...")
        with open(job_config_file, "r", encoding="utf8") as f:
            job_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading job config file: [{job_config_file}]", e)
    try:
        logging.debug(f"Loading env config file: [./saagie/envs/{env}.json] ...")
        with open(f"./saagie/envs/{env}.json", "r", encoding="utf8") as f:
            env_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading env config file: [./saagie/envs/{env}.json]", e)

    release_note = "WIP"
    if "CI" in os.environ:
        release_note = f"{os.environ['CI_COMMIT_MESSAGE']} - {os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/commit/{os.environ['GITHUB_SHA']}"

    res = client_saagie.jobs.create_or_upgrade(
        job_name=job_config["job_name"],
        project_id=env_config["project_id"],
        file=job_config["file_path"] if "file_path" in job_config and bool(job_config["file_path"]) else None,
        description=job_config["description"] if "description" in job_config else "",
        category=job_config["category"] if "category" in job_config else "",
        technology=job_config["technology"] if "technology" in job_config else "",
        technology_catalog=job_config["technology_catalog"] if "technology_catalog" in job_config else "",
        runtime_version=job_config["runtime_version"] if "runtime_version" in job_config and bool(job_config["runtime_version"]) else None,
        command_line=job_config["command_line"] if "command_line" in job_config and bool(job_config["command_line"]) else None,
        release_note=release_note,
        extra_technology=job_config["extra_technology"] if "extra_technology" in job_config else None,
        extra_technology_version=job_config["extra_technology_version"] if "extra_technology_version" in job_config else None
    )
    return res


def run_job(client_saagie, job_config_file, env):
    """
    Run a job on Saagie
    :param client_saagie: SaagieAPI, an instance of SaagieAP
    :param job_config_file: str, job config file path
    :param env: str, environment of Saagie that you want to create or upgrade job
    :return: dict, dict of job instance ID and status
    """
    try:
        logging.debug(f"Loading job config file: [{job_config_file}] ...")
        with open(job_config_file, "r") as f:
            job_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading job config file: [{job_config_file}]", e)
    try:
        logging.debug(f"Loading env config file: [./saagie/envs/{env}.json] ...")
        with open(f"./saagie/envs/{env}.json", "r") as f:
            env_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading env config file: [./saagie/envs/{env}.json]", e)
    logging.debug(f"Getting job ID: [{job_config['job_name']}] ...")
    job_id = client_saagie.jobs.get_id(job_config["job_name"], env_config["project_name"])
    logging.info("Job ID: " + job_id)
    logging.debug(f"Running job: [{job_id}] ...")
    return client_saagie.jobs.run(job_id)


def create_graph(pipeline_config_file, env):
    """
    Create the Graph of Saagie graph pipeline
    :param pipeline_config_file: str, pipeline config file path
    :param env: str, environment of Saagie that you want upgrade pipeline
    :return: saagieapi.GraphPipeline
    """
    file_extension = Path(pipeline_config_file).suffix
    logging.debug(f"Loading pipeline config file: [{pipeline_config_file}] ...")
    if file_extension == ".json":
        with open(pipeline_config_file, "r", encoding="utf8") as f:
            pipeline_config = json.load(f)
    elif file_extension == ".yaml" or file_extension == ".yml":
        with open(pipeline_config_file, "r", encoding="utf8") as f:
            pipeline_config = yaml.safe_load(f)
    else:
        raise Exception("Pipeline artefact file must be a json or yaml file")

    pipeline_info = pipeline_config["env"][env]["graph_pipeline"]
    graph_pipeline = GraphPipeline()
    list_job_nodes = []
    list_condition_nodes = []

    logging.debug("Creating graph pipeline ...")
    logging.debug("Creating job nodes ...")
    # Find all job nodes
    for i in range(len(pipeline_info["job_nodes"])):
        job_node_info = pipeline_info["job_nodes"][i]

        node_dict = {
            "id": job_node_info["id"],
            "job": {"id": job_node_info["job_id"]},
            "nextNodes": job_node_info["next_nodes"],
        }
        list_job_nodes.append(node_dict)

    logging.debug("Creating condition nodes ...")
    # Find all condition nodes
    for i in range(len(pipeline_info["condition_nodes"])):
        condition_node_info = pipeline_info["condition_nodes"][i]

        condition_dict = {
            "id": condition_node_info["id"],
            "nextNodesSuccess": condition_node_info["next_nodes_success"],
            "nextNodesFailure": condition_node_info["next_nodes_failure"],
        }
        if condition_node_info["condition_type"] == "status":
            condition_dict["condition"] = {
                "status": {"value": condition_node_info["value"]}
            }
        elif condition_node_info["condition_type"] == "expression":
            condition_dict["condition"] = {
                "custom": {"expression": condition_node_info["value"]}
            }
        list_condition_nodes.append(condition_dict)
    graph_pipeline.list_job_nodes = list_job_nodes
    graph_pipeline.list_conditions_nodes = list_condition_nodes
    return graph_pipeline


def create_or_upgrade_graph_pipeline(client_saagie, pipeline_config_file, env):
    """
    Create or upgrade pipeline in Saagie
    :param client_saagie: SaagieAPI, an instance of SaagieAPI
    :param pipeline_config_file: str, pipeline config file path
    :param env: str, environment of Saagie that you want upgrade pipeline
    :return: dict of pipeline information
    """
    try:
        with open(pipeline_config_file, "r", encoding="utf8") as f:
            pipeline_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading pipeline config file: [{pipeline_config_file}]", e)

    file_extension = Path(pipeline_config["file_path"]).suffix
    if file_extension == ".json":
        with open(pipeline_config["file_path"], "r", encoding="utf8") as f:
            pipeline_info = json.load(f)
    elif file_extension == ".yaml" or file_extension == ".yml":
        with open(pipeline_config["file_path"], "r", encoding="utf8") as f:
            pipeline_info = yaml.safe_load(f)
    else:
        raise Exception("Pipeline artefact file must be json or yaml file")
    with open(f"./saagie/envs/{env}.json", "r") as f:
        env_config = json.load(f)

    graph_pipeline = create_graph(pipeline_config["file_path"], env)
    release_note = "WIP"
    if "CI" in os.environ:
        release_note = f"{os.environ['CI_COMMIT_MESSAGE']} - {os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/commit/{os.environ['GITHUB_SHA']}"

    res = client_saagie.pipelines.create_or_upgrade(
        name=pipeline_info["pipeline_name"],
        project_id=env_config["project_id"],
        graph_pipeline=graph_pipeline,
        release_note=release_note,
        description=pipeline_info["description"] if "description" in pipeline_info and bool(pipeline_info["description"])else None,
        has_execution_variables_enabled=pipeline_info["has_execution_variables_enabled"] if
        "has_execution_variables_enabled" in pipeline_info and bool(pipeline_info["has_execution_variables_enabled"]) else None,
    )
    return res


def run_pipeline(client_saagie, pipeline_config_file, env):
    """
    Run a pipeline on Saagie
    :param client_saagie: SaagieAPI, an instance of SaagieAP
    :param pipeline_config_file: str, pipeline config file path
    :param env: str, environment of Saagie that you want to create or upgrade job
    :return: dict, dict of job instance ID and status
    """
    try:
        with open(pipeline_config_file, "r") as f:
            pipeline_config = json.load(f)
    except Exception as e:
        return handle_log_error(f"Error when loading pipeline config file: [{pipeline_config_file}]", e)

    file_extension = Path(pipeline_config["file_path"]).suffix
    if file_extension == ".json":
        with open(pipeline_config["file_path"], "r") as f:
            pipeline_info = json.load(f)
    elif file_extension == ".yaml" or file_extension == ".yml":
        with open(pipeline_config["file_path"], "r") as f:
            pipeline_info = yaml.safe_load(f)
    else:
        raise Exception("Pipeline config file must be json or yaml file")

    logging.debug(f"Loading environment config file: ./saagie/envs/{env}.json")
    with open(f"./saagie/envs/{env}.json", "r") as f:
        env_config = json.load(f)
    logging.debug(f"Getting pipeline ID of {pipeline_info['pipeline_name']} ...")
    pipeline_id = client_saagie.pipelines.get_id(project_name=env_config["project_name"], pipeline_name=pipeline_info["pipeline_name"])
    logging.info("Pipeline ID: " + pipeline_id)
    logging.debug(f"Running pipeline: [{pipeline_id}]...")
    return client_saagie.pipelines.run(pipeline_id)
