# -*- coding: utf-8 -*-
"""
Created on Mon Aug  8 16:08:25 2016

@author: del
@author: The Gene Sets Characterization dev team

"""
import os
import time
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import knpackage.toolbox as kn
from multiprocessing import Pool
import itertools
import multiprocessing

from scipy.stats import pearsonr as pcc


def run_nmf(run_parameters):
    """ wrapper: call sequence to perform non-negative matrix factorization and write results.

    Args:
        run_parameters: parameter set dictionary.
    """
    spreadsheet_df = kn.get_spreadsheet_df(run_parameters['spreadsheet_name_full_path'])
    spreadsheet_mat = spreadsheet_df.as_matrix()
    spreadsheet_mat = kn.get_quantile_norm_matrix(spreadsheet_mat)

    h_mat = kn.perform_nmf(spreadsheet_mat, run_parameters)

    linkage_matrix = np.zeros((spreadsheet_mat.shape[1], spreadsheet_mat.shape[1]))
    sample_perm = np.arange(0, spreadsheet_mat.shape[1])
    linkage_matrix = kn.update_linkage_matrix(h_mat, sample_perm, linkage_matrix)
    labels = kn.perform_kmeans(linkage_matrix, run_parameters['number_of_clusters'])

    sample_names = spreadsheet_df.columns
    save_final_samples_clustering(sample_names, labels, run_parameters)

    if run_parameters['display_clusters'] != 0:
        con_mat_image = form_consensus_matrix_graphic(linkage_matrix, run_parameters['number_of_clusters'])
        display_clusters(con_mat_image)

    return


def run_cc_nmf(run_parameters):
    """ wrapper: call sequence to perform non-negative matrix factorization with
        consensus clustering and write results.

    Args:
        run_parameters: parameter set dictionary.
    """
    tmp_dir = 'tmp_cc_nmf'
    run_parameters["tmp_directory"] = kn.create_dir(
        run_parameters["run_directory"], tmp_dir)

    spreadsheet_df = kn.get_spreadsheet_df(run_parameters['spreadsheet_name_full_path'])
    spreadsheet_mat = spreadsheet_df.as_matrix()
    spreadsheet_mat = kn.get_quantile_norm_matrix(spreadsheet_mat)
    if run_parameters['use_parallel_processing'] != 0:
        # Number of processes to be executed in parallel
        number_of_cpus = multiprocessing.cpu_count()
        if (run_parameters["number_of_bootstraps"] < number_of_cpus):
            number_of_cpus = run_parameters["number_of_bootstraps"]
        print("Using parallelism {}".format(number_of_cpus))

        find_and_save_nmf_clusters_parallel(spreadsheet_mat, run_parameters, number_of_cpus)
    else:
        find_and_save_nmf_clusters_serial(spreadsheet_mat, run_parameters)

    linkage_matrix = np.zeros((spreadsheet_mat.shape[1], spreadsheet_mat.shape[1]))
    indicator_matrix = linkage_matrix.copy()
    consensus_matrix = form_consensus_matrix(run_parameters, linkage_matrix, indicator_matrix)
    labels = kn.perform_kmeans(consensus_matrix, run_parameters['number_of_clusters'])

    sample_names = spreadsheet_df.columns
    save_consensus_clustering(consensus_matrix, sample_names, labels, run_parameters)
    save_final_samples_clustering(sample_names, labels, run_parameters)

    kn.remove_dir(run_parameters["tmp_directory"])

    if run_parameters['display_clusters'] != 0:
        display_clusters(form_consensus_matrix_graphic(consensus_matrix, run_parameters['number_of_clusters']))

    return


def run_net_nmf(run_parameters):
    """ wrapper: call sequence to perform network based stratification and write results.

    Args:
        run_parameters: parameter set dictionary.
    """
    spreadsheet_df = kn.get_spreadsheet_df(run_parameters['spreadsheet_name_full_path'])
    network_df = kn.get_network_df(run_parameters['gg_network_name_full_path'])

    node_1_names, node_2_names = kn.extract_network_node_names(network_df)
    unique_gene_names = kn.find_unique_node_names(node_1_names, node_2_names)
    genes_lookup_table = kn.create_node_names_dict(unique_gene_names)

    network_df = kn.map_node_names_to_index(network_df, genes_lookup_table, 'node_1')
    network_df = kn.map_node_names_to_index(network_df, genes_lookup_table, 'node_2')

    network_df = kn.symmetrize_df(network_df)
    network_mat = kn.convert_network_df_to_sparse(
        network_df, len(unique_gene_names), len(unique_gene_names))

    network_mat = kn.normalize_sparse_mat_by_diagonal(network_mat)
    lap_diag, lap_pos = kn.form_network_laplacian_matrix(network_mat)

    spreadsheet_df = kn.update_spreadsheet_df(spreadsheet_df, unique_gene_names)
    spreadsheet_mat = spreadsheet_df.as_matrix()
    sample_names = spreadsheet_df.columns

    sample_smooth, iterations = kn.smooth_matrix_with_rwr(
        spreadsheet_mat, network_mat, run_parameters)
    sample_quantile_norm = kn.get_quantile_norm_matrix(sample_smooth)
    h_mat = kn.perform_net_nmf(sample_quantile_norm, lap_pos, lap_diag, run_parameters)

    linkage_matrix = np.zeros((spreadsheet_mat.shape[1], spreadsheet_mat.shape[1]))
    sample_perm = np.arange(0, spreadsheet_mat.shape[1])
    linkage_matrix = kn.update_linkage_matrix(h_mat, sample_perm, linkage_matrix)
    labels = kn.perform_kmeans(linkage_matrix, run_parameters['number_of_clusters'])

    save_final_samples_clustering(sample_names, labels, run_parameters)

    if run_parameters['display_clusters'] != 0:
        display_clusters(form_consensus_matrix_graphic(linkage_matrix, run_parameters['number_of_clusters']))

    return


def run_cc_net_nmf(run_parameters):
    """ wrapper: call sequence to perform network based stratification with consensus clustering
        and write results.

    Args:
        run_parameters: parameter set dictionary.
    """
    tmp_dir = 'tmp_cc_net_nmf'
    if (run_parameters['processing_method'] == 2):
        # Currently hard coded to jingge's namespace, need to change it once we have a dedicated share location
        run_parameters["tmp_directory"] = kn.create_dir("/mnt/backup/users/jingge/distributed_computing/tmp/", tmp_dir)
    else:
        run_parameters["tmp_directory"] = kn.create_dir(run_parameters["run_directory"], tmp_dir)

    spreadsheet_df = kn.get_spreadsheet_df(run_parameters['spreadsheet_name_full_path'])
    network_df = kn.get_network_df(run_parameters['gg_network_name_full_path'])

    node_1_names, node_2_names = kn.extract_network_node_names(network_df)
    unique_gene_names = kn.find_unique_node_names(node_1_names, node_2_names)
    genes_lookup_table = kn.create_node_names_dict(unique_gene_names)

    network_df = kn.map_node_names_to_index(network_df, genes_lookup_table, 'node_1')
    network_df = kn.map_node_names_to_index(network_df, genes_lookup_table, 'node_2')

    network_df = kn.symmetrize_df(network_df)
    # network_mat = convert_df_to_sparse(network_df, len(unique_gene_names))
    network_mat = kn.convert_network_df_to_sparse(
        network_df, len(unique_gene_names), len(unique_gene_names))

    network_mat = kn.normalize_sparse_mat_by_diagonal(network_mat)
    lap_diag, lap_pos = kn.form_network_laplacian_matrix(network_mat)

    spreadsheet_df = kn.update_spreadsheet_df(spreadsheet_df, unique_gene_names)
    spreadsheet_mat = spreadsheet_df.as_matrix()
    sample_names = spreadsheet_df.columns

    if run_parameters['processing_method'] == 1:
        # Number of processes to be executed in parallel
        number_of_loops = run_parameters['number_of_bootstraps']
        print("Number of bootstrap {}".format(number_of_loops))
        find_and_save_net_nmf_clusters_parallel(network_mat, spreadsheet_mat, lap_diag, lap_pos, run_parameters,number_of_loops)
        print("Finish parallel computing locally......")
    elif run_parameters['processing_method'] == 2:
        print("Start distributing jobs......")
        # determine number of compute nodes to use
        number_of_comptue_nodes = determine_number_of_compute_nodes(run_parameters['cluster_ip_address'],
                                                                    run_parameters['number_of_bootstraps'])
        print("number of compute nodes = {}".format(number_of_comptue_nodes))
        # create clusters
        cluster_list = generate_compute_clusters(run_parameters['cluster_ip_address'][0:number_of_comptue_nodes],
                                                 find_and_save_net_nmf_clusters_parallel,
                                                 [run_net_nmf_clusters_worker,
                                                  save_a_clustering_to_tmp,
                                                  determine_parallelism_locally])
        # calculates number of jobs assigned to each compute node
        number_of_jobs_each_node = determine_job_number_on_each_compute_node(run_parameters['number_of_bootstraps'],
                                                                             len(cluster_list))
        arg_list = [network_mat, spreadsheet_mat, lap_diag, lap_pos, run_parameters]
        # parallel submitting jobs
        parallel_submitting_job_to_each_compute_node(network_mat, spreadsheet_mat, lap_diag, lap_pos, run_parameters,cluster_list, number_of_jobs_each_node)
        #parallel_submitting_job_to_each_compute_node(cluster_list, number_of_jobs_each_node, *arg_list)


        print("Finish distributing jobs......")
    elif run_parameters['processing_method'] == 0:
        find_and_save_net_nmf_clusters_serial(network_mat, spreadsheet_mat, lap_diag, lap_pos, run_parameters)
    else:
        raise ValueError('processing_method contains bad value.')

    linkage_matrix = np.zeros((spreadsheet_mat.shape[1], spreadsheet_mat.shape[1]))
    indicator_matrix = linkage_matrix.copy()
    consensus_matrix = form_consensus_matrix(run_parameters, linkage_matrix, indicator_matrix)
    labels = kn.perform_kmeans(consensus_matrix, run_parameters['number_of_clusters'])

    save_consensus_clustering(consensus_matrix, sample_names, labels, run_parameters)
    save_final_samples_clustering(sample_names, labels, run_parameters)

    kn.remove_dir(run_parameters["tmp_directory"])

    if run_parameters['display_clusters'] != 0:
        display_clusters(form_consensus_matrix_graphic(consensus_matrix, run_parameters['number_of_clusters']))

    return


def create_cluster_worker(cluster, i, network_mat, spreadsheet_mat, lap_diag, lap_pos, run_parameters, number_of_loops):
                #(cluster, i , number_of_loops, *arguments):
    '''
    Submit job to cluster

    Args:
        cluster: current cluster
        i: current index
        network_mat: genes x genes symmetric matrix.
        spreadsheet_mat: genes x samples matrix.
        lap_dag: laplacian matrix component, L = lap_dag - lap_val.
        lap_val: laplacian matrix component, L = lap_dag - lap_val.
        run_parameters: dictionay of run-time parameters.
        number_of_loops: total number of loops will be run on the current job

    Returns:

    '''
    import sys
    print("Start creating clusters {}.....".format(str(i)))
    try:
        job = cluster.submit(network_mat, spreadsheet_mat, lap_diag, lap_pos, run_parameters, number_of_loops)
        #job = cluster.submit(number_of_loops, *arguments)
        job.id = i
        ret = job()
        print(ret, job.stdout, job.stderr, job.exception, job.ip_addr, job.start_time, job.end_time)
    except:
        print(sys.exc_info())


def parallel_submitting_job_to_each_compute_node(network_mat, spreadsheet_mat, lap_dag, lap_val, run_parameters, cluster_list, number_of_jobs_each_node):
               # (cluster_list, number_of_jobs_each_node, *arguments):

    '''
    Parallel submitting jobs to each node and start computation

    Args:
        network_mat: genes x genes symmetric matrix.
        spreadsheet_mat: genes x samples matrix.
        lap_dag: laplacian matrix component, L = lap_dag - lap_val.
        lap_val: laplacian matrix component, L = lap_dag - lap_val.
        run_parameters: dictionay of run-time parameters.
        cluster_list: a list of clusters that will be used run distribute jobs
        number_of_jobs_each_node: a list of numbers indicates the number of jobs assigned to each compute node

    Returns:

    '''
    import threading
    import sys

    thread_list = []
    print("Start spawning {} threads.....".format(len(cluster_list)))
    try:
        for i in range(len(cluster_list)):
            t = threading.Thread(target=create_cluster_worker, args=(
                cluster_list[i], i, network_mat, spreadsheet_mat, lap_dag, lap_val, run_parameters,
                number_of_jobs_each_node[i]))
            thread_list.append(t)
            t.start()

        for thread in thread_list:
            thread.join()

        for cluster in cluster_list:
            cluster.print_status()

        for cluster in cluster_list:
            cluster.close()
    except:
        raise OSError(sys.exc_info())


def generate_compute_clusters(cluster_ip_addresses, func_name, dependency_list):
    '''
    Generate clusters based on given list of ip address

    Args:
        cluster_ip_addresses: a list of ip address
        func_name: function name
        dependency_list: the dependencies for running the current function

    Returns:
        cluster_list: a list of clusters as dispy object

    '''
    import sys
    import dispy
    import logging
    try:
        cluster_list = []
        range_list = range(0, len(cluster_ip_addresses))
        print(range_list)
        for i in range_list:
            cur_cluster = dispy.JobCluster(func_name,
                                           nodes=[cluster_ip_addresses[i]],
                                           depends=dependency_list,
                                           loglevel=logging.WARNING)
            cluster_list.append(cur_cluster)
        return cluster_list
    except:
        raise OSError(sys.exc_info())


def determine_number_of_compute_nodes(cluster_ip_addresses, number_of_bootstraps):
    '''
    Determine the total number of compute nodes will be used in execution

    Args:
        cluster_ip_addresses: a list of ip address
        number_of_bootstraps:  total number of loops needs to be distributed across clusters

    Returns:
        number_of_compute_nodes: the number of compute nodes

    '''
    available_computing_nodes = len(cluster_ip_addresses)

    if (number_of_bootstraps < available_computing_nodes):
        number_of_compute_nodes = number_of_bootstraps
    else:
        number_of_compute_nodes = available_computing_nodes

    return number_of_compute_nodes


def determine_job_number_on_each_compute_node(number_of_bootstraps, number_of_compute_nodes):
    '''
    Determine total number of jobs run on each compute node

    Args:
        number_of_bootstraps: total number of loops needs to be distributed across compute nodes
        number_of_compute_nodes: total number of available compute nodes

    Returns:
        number_of_scheduled_jobs: a list of integer indicates number of jobs distribution across compute nodes

    '''
    number_of_jobs_on_single_node = int(number_of_bootstraps / number_of_compute_nodes)
    remainder_of_jobs = number_of_bootstraps % number_of_compute_nodes

    number_of_scheduled_jobs = []
    if remainder_of_jobs > 0:
        count = 0
        for i in range(number_of_compute_nodes):
            if (count < remainder_of_jobs):
                number_of_scheduled_jobs.append(number_of_jobs_on_single_node + 1)
            else:
                number_of_scheduled_jobs.append(number_of_jobs_on_single_node)
            count += 1
    else:
        for i in range(number_of_compute_nodes):
            number_of_scheduled_jobs.append(number_of_jobs_on_single_node)

    print("number_of_scheduled_jobs across clusters : {}".format(number_of_scheduled_jobs))
    return number_of_scheduled_jobs


def determine_parallelism_locally(number_of_loops):
    '''
    Determine the parallelism on the current compute node
    
    Args:
        number_of_loops: total number of loops will be executed on current compute node

    Returns:
        number_of_cpu: parallelism on current compute node

    '''
    import multiprocessing
    number_of_cpu = multiprocessing.cpu_count()
    if (number_of_loops < number_of_cpu):
        return number_of_loops
    else:
        return number_of_cpu


def run_net_nmf_clusters_worker(network_mat, spreadsheet_mat, lap_dag, lap_val, run_parameters, sample):
    """Worker to execute net_nmf_clusters in a single process

    Args:
        network_mat: genes x genes symmetric matrix.
        spreadsheet_mat: genes x samples matrix.
        lap_dag: laplacian matrix component, L = lap_dag - lap_val.
        lap_val: laplacian matrix component, L = lap_dag - lap_val.
        run_parameters: dictionay of run-time parameters.
        sample: each single loop.

    Returns:
        None
    """
    import knpackage.toolbox as kn
    import numpy as np

    sample_random, sample_permutation = kn.sample_a_matrix(
        spreadsheet_mat, run_parameters["rows_sampling_fraction"],
        run_parameters["cols_sampling_fraction"])
    sample_smooth, iterations = \
        kn.smooth_matrix_with_rwr(sample_random, network_mat, run_parameters)

    print("bootstrap {} of {}: rwr iterations = {}".format(sample + 1, run_parameters["number_of_bootstraps"],
                                                           iterations))

    sample_quantile_norm = kn.get_quantile_norm_matrix(sample_smooth)
    h_mat = kn.perform_net_nmf(sample_quantile_norm, lap_val, lap_dag, run_parameters)

    save_a_clustering_to_tmp(h_mat, sample_permutation, run_parameters, sample)


def find_and_save_net_nmf_clusters_serial(network_mat, spreadsheet_mat, lap_dag, lap_val, run_parameters):
    """ central loop: compute components for the consensus matrix from the input
        network and spreadsheet matrices and save them to temp files.

    Args:
        network_mat: genes x genes symmetric matrix.
        spreadsheet_mat: genes x samples matrix.
        lap_dag: laplacian matrix component, L = lap_dag - lap_val.
        lap_val: laplacian matrix component, L = lap_dag - lap_val.
        run_parameters: dictionary of run-time parameters.
    """
    number_of_bootstraps = run_parameters["number_of_bootstraps"]
    for sample in range(0, number_of_bootstraps):
        run_net_nmf_clusters_worker(network_mat, spreadsheet_mat, lap_dag, lap_val, run_parameters, sample)


def find_and_save_net_nmf_clusters_parallel(network_mat, spreadsheet_mat, lap_dag, lap_val, run_parameters, number_of_loops):
    """ central loop: compute components for the consensus matrix from the input
        network and spreadsheet matrices and save them to temp files.

    Args:
        network_mat: genes x genes symmetric matrix.
        spreadsheet_mat: genes x samples matrix.
        lap_dag: laplacian matrix component, L = lap_dag - lap_val.
        lap_val: laplacian matrix component, L = lap_dag - lap_val.
        run_parameters: dictionary of run-time parameters.
        number_of_cpus: number of processes to be running in parallel
    """
    import multiprocessing
    import itertools
    import sys
    import socket

    try:
        parallelism = determine_parallelism_locally(number_of_loops)

        host = socket.gethostname()
        print("Using parallelism {} on host {}.....".format(parallelism, host))

        range_list = range(0, number_of_loops)
        p = multiprocessing.Pool(processes=parallelism)
        p.starmap(run_net_nmf_clusters_worker,
                  zip(itertools.repeat(network_mat),
                      itertools.repeat(spreadsheet_mat),
                      itertools.repeat(lap_dag),
                      itertools.repeat(lap_val),
                      itertools.repeat(run_parameters),
                      range_list))
        p.close()
        p.join()

        return "Succeeded running parallel processing on node {}.".format(host)
    except:
        raise OSError("Failed running parallel processing on node {}: {}".format(host, sys.exc_info()))


def run_nmf_clusters_worker(spreadsheet_mat, run_parameters, sample):
    """Worker to execute nmf_clusters in a single process

    Args:
        spreadsheet_mat: genes x samples matrix.
        run_parameters: dictionary of run-time parameters.
        sample: each loops.

    Returns:
        None

    """
    sample_random, sample_permutation = kn.sample_a_matrix(
        spreadsheet_mat, run_parameters["rows_sampling_fraction"],
        run_parameters["cols_sampling_fraction"])

    h_mat = kn.perform_nmf(sample_random, run_parameters)
    save_a_clustering_to_tmp(h_mat, sample_permutation, run_parameters, sample)

    print('bootstrap {} of {}'.format(sample + 1, run_parameters["number_of_bootstraps"]))


def find_and_save_nmf_clusters_serial(spreadsheet_mat, run_parameters):
    """ central loop: compute components for the consensus matrix by
        non-negative matrix factorization.

    Args:
        spreadsheet_mat: genes x samples matrix.
        run_parameters: dictionary of run-time parameters.
    """
    number_of_bootstraps = run_parameters["number_of_bootstraps"]

    for sample in range(0, number_of_bootstraps):
        run_nmf_clusters_worker(spreadsheet_mat, run_parameters, sample)


def find_and_save_nmf_clusters_parallel(spreadsheet_mat, run_parameters, number_of_cpus):
    """ central loop: compute components for the consensus matrix by
        non-negative matrix factorization.

    Args:
        spreadsheet_mat: genes x samples matrix.
        run_parameters: dictionary of run-time parameters.
        number_of_cpus: number of processes to be running in parallel
    """
    number_of_bootstraps = run_parameters["number_of_bootstraps"]
    p = Pool(processes=number_of_cpus)
    range_list = range(0, number_of_bootstraps)
    p.starmap(run_nmf_clusters_worker,
              zip(itertools.repeat(spreadsheet_mat),
                  itertools.repeat(run_parameters),
                  range_list))

    p.close()
    p.join()


def form_consensus_matrix(run_parameters, linkage_matrix, indicator_matrix):
    """ compute the consensus matrix from the indicator and linkage matrix inputs
        formed by the bootstrap "temp_*" files.

    Args:
        run_parameters: parameter set dictionary with "tmp_directory" key.
        linkage_matrix: linkage matrix from initialization or previous call.
        indicator_matrix: indicator matrix from initialization or previous call.

    Returns:
        consensus_matrix: (sum of linkage matrices) / (sum of indicator matrices).
    """
    indicator_matrix = get_indicator_matrix(run_parameters, indicator_matrix)
    linkage_matrix = get_linkage_matrix(run_parameters, linkage_matrix)
    consensus_matrix = linkage_matrix / np.maximum(indicator_matrix, 1)

    return consensus_matrix


def get_indicator_matrix(run_parameters, indicator_matrix):
    """ read bootstrap temp_p* files and compute the indicator_matrix.

    Args:
        run_parameters: parameter set dictionary.
        indicator_matrix: indicator matrix from initialization or previous call.

    Returns:
        indicator_matrix: input summed with "temp_p*" files in run_parameters["tmp_directory"].
    """
    tmp_dir = run_parameters["tmp_directory"]
    dir_list = os.listdir(tmp_dir)
    for tmp_f in dir_list:
        if tmp_f[0:6] == 'temp_p':
            pname = os.path.join(tmp_dir, tmp_f)
            sample_permutation = np.load(pname)
            indicator_matrix = kn.update_indicator_matrix(sample_permutation, indicator_matrix)

    return indicator_matrix


def get_linkage_matrix(run_parameters, linkage_matrix):
    """ read bootstrap temp_h* and temp_p* files, compute and add the linkage_matrix.

    Args:
        run_parameters: parameter set dictionary.
        linkage_matrix: connectivity matrix from initialization or previous call.

    Returns:
        linkage_matrix: summed with "temp_h*" files in run_parameters["tmp_directory"].
    """
    tmp_dir = run_parameters["tmp_directory"]
    dir_list = os.listdir(tmp_dir)
    for tmp_f in dir_list:
        if tmp_f[0:6] == 'temp_p':
            pname = os.path.join(tmp_dir, tmp_f)
            sample_permutation = np.load(pname)
            hname = os.path.join(tmp_dir, tmp_f[0:5] + 'h' + tmp_f[6:len(tmp_f)])
            h_mat = np.load(hname)
            linkage_matrix = kn.update_linkage_matrix(h_mat, sample_permutation, linkage_matrix)

    return linkage_matrix


def save_a_clustering_to_tmp(h_matrix, sample_permutation, run_parameters, sequence_number):
    """ save one h_matrix and one permutation in temorary files with sequence_number appended names.

    Args:
        h_matrix: k x permutation size matrix.
        sample_permutation: indices of h_matrix columns permutation.
        run_parameters: parmaeters including the "tmp_directory" name.
        sequence_number: temporary file name suffix.
    """
    import os
    import sys
    import knpackage.toolbox as kn
    import numpy as np

    tmp_dir = run_parameters["tmp_directory"]
    # time_stamp = timestamp_filename('_N', str(sequence_number), run_parameters)
    time_stamp = kn.create_timestamped_filename('_N' + str(sequence_number), name_extension=None, precision=1e12)

    hname = os.path.join(tmp_dir, 'temp_h' + time_stamp)
    pname = os.path.join(tmp_dir, 'temp_p' + time_stamp)

    cluster_id = np.argmax(h_matrix, 0)
    with open(hname, 'wb') as fh0:
        cluster_id.dump(fh0)
    with open(pname, 'wb') as fh1:
        sample_permutation.dump(fh1)

    return


def form_consensus_matrix_graphic(consensus_matrix, k=3):
    """ use K-means to reorder the consensus matrix for graphic display.

    Args:
        consensus_matrix: calculated consensus matrix in samples x samples order.
        k: number of clusters estimate (inner diminsion k of factored h_matrix).

    Returns:
        cc_cm: consensus_matrix with rows and columns in K-means sort order.
    """
    cc_cm = consensus_matrix.copy()
    labels = kn.perform_kmeans(consensus_matrix, k)
    sorted_labels = np.argsort(labels)
    cc_cm = cc_cm[sorted_labels[:, None], sorted_labels]

    return cc_cm


def display_clusters(consensus_matrix):
    """ graphic display the consensus matrix.

    Args:
         consenus matrix: usually a smallish square matrix.
    """
    methods = [None, 'none', 'nearest', 'bilinear', 'bicubic', 'spline16',
               'spline36', 'hanning', 'hamming', 'hermite', 'kaiser', 'quadric',
               'catrom', 'gaussian', 'bessel', 'mitchell', 'sinc', 'lanczos']
    grid = consensus_matrix
    fig, axes = plt.subplots(3, 6, figsize=(12, 6),
                             subplot_kw={'xticks': [], 'yticks': []})
    fig.subplots_adjust(hspace=0.3, wspace=0.05)
    for ax_n, interp_method in zip(axes.flat, methods):
        ax_n.imshow(grid, interpolation=interp_method)
        ax_n.set_title(interp_method)
    plt.show()

    return


def save_consensus_clustering(consensus_matrix, sample_names, labels, run_parameters):
    """ write the consensus matrix as a dataframe with sample_names column lablels
        and cluster labels as row labels.

    Args:
        consensus_matrix: sample_names x sample_names numerical matrix.
        sample_names: data identifiers for column names.
        labels: cluster numbers for row names.
        run_parameters: path to write to consensus_data file (run_parameters["results_directory"]).
    """
    file_name = os.path.join(run_parameters["results_directory"],
                             kn.create_timestamped_filename('consensus_data', 'df'))
    out_df = pd.DataFrame(data=consensus_matrix, columns=sample_names, index=labels)
    out_df.to_csv(file_name, sep='\t')
    run_parameters['consensus_clustering_file'] = file_name

    return


def save_final_samples_clustering(sample_names, labels, run_parameters):
    """ wtite .tsv file that assings a cluster number label to the sample_names.

    Args:
        sample_names: (unique) data identifiers.
        labels: cluster number assignments.
        run_parameters: write path (run_parameters["results_directory"]).
    """
    file_name = os.path.join(run_parameters["results_directory"], kn.create_timestamped_filename('labels_data', 'tsv'))
    df_tmp = kn.create_df_with_sample_labels(sample_names, labels)
    df_tmp.to_csv(file_name, sep='\t', header=None)
    run_parameters['cluster_labels_file'] = file_name

    return
