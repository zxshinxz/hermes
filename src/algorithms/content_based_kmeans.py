import numpy as np
from pyspark.mllib.clustering import KMeans
import recommender_helpers as rechelp
from numpy.linalg import norm


def predict(user_info, content_array, num_predictions, k=10, num_partitions=20):
    """Predict ratings for items using a k-means clustering content based
    algorithm designed to increase the diversity of recommended items.

    User profiles are generated by weighting the item vectors by the user's
    rating of the item and summing them.

    The clustering is performed on the item vectors. Items are then drawn from
    these clusters in proportion to the clusters prevalence in the dataset.

    Args:
        user_info (rdd): in the format of (user, item, rating)
        content_array (rdd): content feature array of the items which should be in
            the format of (item, [content_feature vector])
        num_predictions (int): Number of predictions to return

    Returns:
        rdd: in the format of (user, item, predicted_rating)
    """
    # Extract the vectors from the content array
    vectors = content_array.values()
    cluster_model = KMeans.train(vectors, k)
    clustered_content = content_array\
        .map(lambda (item, vector): (cluster_model.predict(vector), (item, vector)))

    cluster_centers = cluster_model.centers

    # Calculate the percent of recommendations to make from each cluster
    counts = clustered_content.countByKey()
    fractions = {}
    total = sum([v for k,v in counts.iteritems()])
    for k, v in counts.iteritems():
        fractions[k] = round(float(v) / total, 2)

    # Make the user profiles
    user_keys = user_info.map(lambda (user, item, rating): (item, (user, rating)))
    user_prefs = content_array\
        .join(user_keys).\
        groupBy(lambda (item, ((item_vector), (user, rating))): user)\
        .map(lambda(user, array): (user, rechelp.sum_components(array)))

    # Make predictions
    max_rating = user_info.map(lambda (user, item, rating): rating).max()
    min_rating = user_info.map(lambda (user, item, rating): rating).min()
    diff_ratings = max_rating - min_rating
    content_and_profiles = clustered_content.cartesian(user_prefs).coalesce(num_partitions)
    predictions_with_clusters = content_and_profiles\
        .map(
            lambda (
                (cluster, (item, item_vector)),
                (user, user_vector)
            ): (
                user,
                cluster,
                item,
                round(np.dot(user_vector, item_vector)/(norm(item_vector)*norm(user_vector)), 3)
            )
        )

    clustered_predictions = predictions_with_clusters\
        .groupBy(lambda (user, cluster, item, rating): (user, cluster))\
        .flatMap(lambda row: rechelp.sort_and_cut_by_cluster(row, num_predictions, fractions))\
        .map(lambda (user, rating, item): (user, item, rating))

    max_pred = clustered_predictions.map(lambda (user,item, pred):pred).max()
    min_pred = clustered_predictions.map(lambda (user,item, pred):pred).min()

    diff_pred = float(max_pred - min_pred)

    norm_predictions = clustered_predictions.map(lambda (user,item, pred):(user, item, \
                    (pred-min_pred)*float(diff_ratings/diff_pred)+min_rating))

    return norm_predictions
