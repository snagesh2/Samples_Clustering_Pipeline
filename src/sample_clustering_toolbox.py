"""
@author: The KnowEnG dev team
"""
import os
import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_score
import knpackage.toolbox as kn
import knpackage.distributed_computing_utils as dstutil


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
    save_spreadsheet_and_variance_heatmap(spreadsheet_df, labels, run_parameters)

    return


def run_cc_nmf(run_parameters):
    """ wrapper: call sequence to perform non-negative matrix factorization with
        consensus clustering and write results.

    Args:
        run_parameters: parameter set dictionary.
    """
    tmp_dir = 'tmp_cc_nmf'
    run_parameters = update_tmp_directory(run_parameters, tmp_dir)

    spreadsheet_df = kn.get_spreadsheet_df(run_parameters['spreadsheet_name_full_path'])
    spreadsheet_mat = spreadsheet_df.as_matrix()
    spreadsheet_mat = kn.get_quantile_norm_matrix(spreadsheet_mat)

    if run_parameters['processing_method'] == 'parl_loc':
        # Number of processes to be executed in parallel
        number_of_loops = run_parameters["number_of_bootstraps"]

        find_and_save_nmf_clusters_parallel(spreadsheet_mat, run_parameters, number_of_loops)
    elif run_parameters['processing_method'] == 'dist_comp':
        print("Start distributing jobs......")

        # determine number of compute nodes to use
        number_of_comptue_nodes = dstutil.determine_number_of_compute_nodes(run_parameters['cluster_ip_address'],
                                                                            run_parameters['number_of_bootstraps'])
        print("Number of compute nodes = {}".format(number_of_comptue_nodes))
        # create clusters
        cluster_list = dstutil.generate_compute_clusters(
            run_parameters['cluster_ip_address'][0:number_of_comptue_nodes],
            find_and_save_nmf_clusters_parallel,
            [run_nmf_clusters_worker,
             save_a_clustering_to_tmp,
             dstutil.determine_parallelism_locally])

        # calculates number of jobs assigned to each compute node
        number_of_jobs_each_node = dstutil.determine_job_number_on_each_compute_node(
            run_parameters['number_of_bootstraps'],
            len(cluster_list))

        # defines the number of arguments pass to worker function
        func_args = [spreadsheet_mat, run_parameters]

        # parallel submitting jobs
        dstutil.parallel_submitting_job_to_each_compute_node(cluster_list, number_of_jobs_each_node, *func_args)

        print("Finish distributing jobs......")
    elif run_parameters['processing_method'] == 'serial':
        find_and_save_nmf_clusters_serial(spreadsheet_mat, run_parameters)
    else:
        raise ValueError('processing_method contains bad value.')

    linkage_matrix = np.zeros((spreadsheet_mat.shape[1], spreadsheet_mat.shape[1]))
    indicator_matrix = linkage_matrix.copy()
    consensus_matrix = form_consensus_matrix(run_parameters, linkage_matrix, indicator_matrix)
    labels = kn.perform_kmeans(consensus_matrix, run_parameters['number_of_clusters'])

    sample_names = spreadsheet_df.columns
    save_consensus_clustering(consensus_matrix, sample_names, labels, run_parameters)
    save_final_samples_clustering(sample_names, labels, run_parameters)
    save_spreadsheet_and_variance_heatmap(spreadsheet_df, labels, run_parameters)

    kn.remove_dir(run_parameters["tmp_directory"])

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
    save_spreadsheet_and_variance_heatmap(spreadsheet_df, labels, run_parameters, network_mat)

    return


def update_tmp_directory(run_parameters, tmp_dir):
    ''' Update tmp_directory value in rum_parameters dictionary

    Args:
        run_parameters: run_parameters as the dictionary config
        tmp_dir: temporary directory prefix subjected to different functions

    Returns:
        run_parameters: an updated run_parameters

    '''
    if (run_parameters['processing_method'] == 'dist_comp'):
        # Currently hard coded to AWS's namespace, need to change it once we have a dedicated share location
        run_parameters["tmp_directory"] = kn.create_dir(run_parameters['cluster_shared_volumn'], tmp_dir)
    else:
        run_parameters["tmp_directory"] = kn.create_dir(run_parameters["run_directory"], tmp_dir)
    return run_parameters


def run_cc_net_nmf(run_parameters):
    """ wrapper: call sequence to perform network based stratification with consensus clustering
        and write results.

    Args:
        run_parameters: parameter set dictionary.
    """
    tmp_dir = 'tmp_cc_net_nmf'
    run_parameters = update_tmp_directory(run_parameters, tmp_dir)

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

    if run_parameters['processing_method'] == 'parl_loc':
        # Number of processes to be executed in parallel
        number_of_loops = run_parameters['number_of_bootstraps']
        print("Number of bootstrap {}".format(number_of_loops))
        find_and_save_net_nmf_clusters_parallel(network_mat, spreadsheet_mat, lap_diag, lap_pos, run_parameters,
                                                number_of_loops)
        print("Finish parallel computing locally......")
    elif run_parameters['processing_method'] == 'dist_comp':
        print("Start distributing jobs......")

        # determine number of compute nodes to use
        number_of_comptue_nodes = dstutil.determine_number_of_compute_nodes(run_parameters['cluster_ip_address'],
                                                                            run_parameters['number_of_bootstraps'])
        print("Number of compute nodes = {}".format(number_of_comptue_nodes))
        # create clusters
        cluster_list = dstutil.generate_compute_clusters(
            run_parameters['cluster_ip_address'][0:number_of_comptue_nodes],
            find_and_save_net_nmf_clusters_parallel,
            [run_net_nmf_clusters_worker,
             save_a_clustering_to_tmp,
             dstutil.determine_parallelism_locally])

        # calculates number of jobs assigned to each compute node
        number_of_jobs_each_node = dstutil.determine_job_number_on_each_compute_node(
            run_parameters['number_of_bootstraps'],
            len(cluster_list))

        # defines the number of arguments pass to worker function
        func_args = [network_mat, spreadsheet_mat, lap_diag, lap_pos, run_parameters]

        # parallel submitting jobs
        dstutil.parallel_submitting_job_to_each_compute_node(cluster_list, number_of_jobs_each_node, *func_args)

        print("Finish distributing jobs......")
    elif run_parameters['processing_method'] == 'serial':
        find_and_save_net_nmf_clusters_serial(network_mat, spreadsheet_mat, lap_diag, lap_pos, run_parameters)
    else:
        raise ValueError('processing_method contains bad value.')

    linkage_matrix = np.zeros((spreadsheet_mat.shape[1], spreadsheet_mat.shape[1]))
    indicator_matrix = linkage_matrix.copy()
    consensus_matrix = form_consensus_matrix(run_parameters, linkage_matrix, indicator_matrix)
    labels = kn.perform_kmeans(consensus_matrix, run_parameters['number_of_clusters'])

    save_consensus_clustering(consensus_matrix, sample_names, labels, run_parameters)
    save_final_samples_clustering(sample_names, labels, run_parameters)
    save_spreadsheet_and_variance_heatmap(spreadsheet_df, labels, run_parameters, network_mat)

    kn.remove_dir(run_parameters["tmp_directory"])

    return


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

    sample_random, sample_permutation = kn.sample_a_matrix(
        spreadsheet_mat, float(run_parameters["rows_sampling_fraction"]),
        float(run_parameters["cols_sampling_fraction"]))
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


def find_and_save_net_nmf_clusters_parallel(network_mat, spreadsheet_mat, lap_dag, lap_val, run_parameters,
                                            number_of_loops):
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
    import knpackage.distributed_computing_utils as dstutil

    try:
        parallelism = dstutil.determine_parallelism_locally(number_of_loops)

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
    import knpackage.toolbox as kn

    sample_random, sample_permutation = kn.sample_a_matrix(
        spreadsheet_mat, float(run_parameters["rows_sampling_fraction"]),
        float(run_parameters["cols_sampling_fraction"]))

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


def find_and_save_nmf_clusters_parallel(spreadsheet_mat, run_parameters, number_of_loops):
    """ central loop: compute components for the consensus matrix by
        non-negative matrix factorization.

    Args:
        spreadsheet_mat: genes x samples matrix.
        run_parameters: dictionary of run-time parameters.
        number_of_cpus: number of processes to be running in parallel
    """
    import multiprocessing
    import itertools
    import sys
    import socket
    import knpackage.distributed_computing_utils as dstutil

    try:
        parallelism = dstutil.determine_parallelism_locally(number_of_loops)

        host = socket.gethostname()
        print("Using parallelism {} on host {}.....".format(parallelism, host))

        number_of_bootstraps = run_parameters["number_of_bootstraps"]
        range_list = range(0, number_of_bootstraps)

        p = multiprocessing.Pool(processes=parallelism)
        p.starmap(run_nmf_clusters_worker,
                  zip(itertools.repeat(spreadsheet_mat),
                      itertools.repeat(run_parameters),
                      range_list))

        p.close()
        p.join()
        return "Succeeded running parallel processing on node {}.".format(host)
    except:
        raise OSError("Failed running parallel processing on node {}: {}".format(host, sys.exc_info()))


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
    if run_parameters['processing_method'] == 'dist_comp':
        tmp_dir = os.path.join(run_parameters['cluster_shared_volumn'],
                               os.path.basename(os.path.normpath(run_parameters['tmp_directory'])))
    else:
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
    if run_parameters['processing_method'] == 'dist_comp':
        tmp_dir = os.path.join(run_parameters['cluster_shared_volumn'],
                               os.path.basename(os.path.normpath(run_parameters['tmp_directory'])))
    else:
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
    os.makedirs(tmp_dir, mode=0o755, exist_ok=True)

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


def save_consensus_clustering(consensus_matrix, sample_names, labels, run_parameters):
    """ write the consensus matrix as a dataframe with sample_names column lablels
        and cluster labels as row labels.

    Args:
        consensus_matrix: sample_names x sample_names numerical matrix.
        sample_names: data identifiers for column names.
        labels: cluster numbers for row names.
        run_parameters: path to write to consensus_data file (run_parameters["results_directory"]).
    """
    out_df = pd.DataFrame(data=consensus_matrix, columns=sample_names, index=sample_names)
    out_df.to_csv(get_output_file_name(run_parameters, 'consensus_data'), sep='\t')

    silhouette_average = silhouette_score(consensus_matrix, labels)
    silhouette_score_string = 'silhouette number of clusters = %d, corresponding silhouette score = %g' % (
        run_parameters['number_of_clusters'], silhouette_average)

    with open(get_output_file_name(run_parameters, 'silhouette_average'), 'w') as fh:
        fh.write(silhouette_score_string)

    return


def save_final_samples_clustering(sample_names, labels, run_parameters):
    """ wtite .tsv file that assings a cluster number label to the sample_names.

    Args:
        sample_names: (unique) data identifiers.
        labels: cluster number assignments.
        run_parameters: write path (run_parameters["results_directory"]).
    """
    file_name = os.path.join(run_parameters["results_directory"], kn.create_timestamped_filename('labels_data', 'tsv'))
    cluster_labels_df = pd.DataFrame(data=None, index=None, columns=['Gene_ID', 'Cluster_ID'])
    cluster_labels_df['Gene_ID'] = sample_names
    cluster_labels_df['Cluster_ID'] = labels
    cluster_labels_df.to_csv(file_name, sep='\t', index=None)

    if 'phenotype_data_full_path' in run_parameters.keys():
        phenotype_data = pd.read_csv(run_parameters['phenotype_data_full_path'], index_col=0, header=0, sep='\t')
        phenotype_data.insert(0, 'Cluster_ID', 'NA')
        phenotype_data.loc[sample_names, 'Cluster_ID'] = labels

        phenotype_data.to_csv(get_output_file_name(run_parameters, 'phenotype_data'), sep='\t', header=True, index=True, na_rep='NA')
    return


def save_spreadsheet_and_variance_heatmap(spreadsheet_df, labels, run_parameters, network_mat=None):
    """ save the full genes by samples spreadsheet as processed or smoothed if network is provided.
        Also save variance in separate file.
    Args:
        spreadsheet_df:
        run_parameters:
        network_mat:    (optional)
    Returns:            (writes files)

    """
    if network_mat is not None:
        sample_smooth, nun = kn.smooth_matrix_with_rwr(spreadsheet_df.as_matrix(), network_mat, run_parameters)
        clusters_df = pd.DataFrame(sample_smooth, index=spreadsheet_df.index.values, columns=spreadsheet_df.columns.values)
    else:
        clusters_df = spreadsheet_df

    clusters_df.to_csv(get_output_file_name(run_parameters, 'gene_by_samples', 'viz'), sep='\t')

    cluster_ave_df = pd.DataFrame({i: spreadsheet_df.iloc[:, labels == i].mean(axis=1) for i in np.unique(labels)})
    col_labels = []
    for cluster_number in np.unique(labels):
        col_labels.append('Cluster_%d'%(cluster_number))
    cluster_ave_df.columns = col_labels
    cluster_ave_df.to_csv(get_output_file_name(run_parameters, 'gene_cluster_average', 'viz'), sep='\t',
                          index_label='Gene_ID')

    clusters_variance_df = pd.DataFrame(clusters_df.var(axis=1), columns=['variance'])
    clusters_variance_df.to_csv(get_output_file_name(run_parameters, 'gene_samples_variance', 'viz'), sep='\t',
                                index_label='Gene_ID')

    top_n_df = pd.DataFrame(data=np.zeros((cluster_ave_df.shape)), columns=cluster_ave_df.columns,
                            index=cluster_ave_df.index.values)
    if 'top_number_of_genes' in run_parameters:
        top_n = run_parameters['top_number_of_genes']
    else:
        top_n = 100
    for sample in top_n_df.columns.values:
        top_index = np.argsort(cluster_ave_df[sample].values)[::-1]
        top_n_df[sample].iloc[top_index[0:top_n]] = 1
    top_n_df.to_csv(get_output_file_name(run_parameters, 'top_genes_for_cluster', 'viz'), sep='\t',
                    index_label='Gene_ID')
    return


def get_output_file_name(run_parameters, prefix_string, suffix_string='', type_suffix='tsv'):
    """ get the full directory / filename for writing
    Args:
        run_parameters: dictionary with keys: "results_directory", "method" and "correlation_measure"
        prefix_string:  the first letters of the ouput file name
        suffix_string:  the last letters of the output file name before '.tsv'

    Returns:
        output_file_name:   full file and directory name suitable for file writing
    """
    output_file_name = os.path.join(run_parameters["results_directory"], prefix_string + '_' + run_parameters['method'])
    output_file_name = kn.create_timestamped_filename(output_file_name) + '_' + suffix_string + '.' + type_suffix

    return output_file_name