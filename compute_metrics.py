import json
from collections import Counter
import argparse
import pandas as pd
from matplotlib import pyplot as plt


def get_acceptance_results(records, target_model_a, target_model_b):
    acceptance_results = {
        target_model_a: {},
        target_model_b: {},
    }
    for record in records:
        instance_id = record.instance_id
        if instance_id not in acceptance_results[record.model_a]:
            acceptance_results[record.model_a][instance_id] = []
        acceptance_results[record.model_a][instance_id].append(record.completion_a_is_acceptable)

        if instance_id not in acceptance_results[record.model_b]:
            acceptance_results[record.model_b][instance_id] = []
        acceptance_results[record.model_b][instance_id].append(record.completion_b_is_acceptable)

    # count how many instances get multiple annotations
    instances_with_multiple_annotations = [instance_id for instance_id, results in acceptance_results[record.model_a].items() if len(results) > 1]
    agreement_results = {
        "num_instances_with_multiple_annotations": len(instances_with_multiple_annotations),
        "acceptance_agreement": None,
    }
    assert target_model_a in acceptance_results
    assert target_model_b in acceptance_results
    # get agreement on acceptance
    if len(instances_with_multiple_annotations) > 0:
        agreed_model_a_acceptance = 0
        agreed_model_b_acceptance = 0
        for instance_id in instances_with_multiple_annotations:
            if len(set(acceptance_results[target_model_a][instance_id][:2])) == 1:
                agreed_model_a_acceptance += 1
            if len(set(acceptance_results[target_model_b][instance_id][:2])) == 1:
                agreed_model_b_acceptance += 1
        agreement_results["acceptance_agreement"] = \
            (agreed_model_a_acceptance + agreed_model_b_acceptance) / (2 * len(instances_with_multiple_annotations))
        agreement_results[f"{target_model_a}_acceptance_agreement"] = agreed_model_a_acceptance / len(instances_with_multiple_annotations)
        agreement_results[f"{target_model_b}_acceptance_agreement"] = agreed_model_b_acceptance / len(instances_with_multiple_annotations)

    # print("Num of results for {}: {}".format(target_model_a, len(acceptance_results[target_model_a])))
    # print("Num of results for {}: {}".format(target_model_b, len(acceptance_results[target_model_b])))
    return {
        f"{target_model_a}": sum([1 if x[0]=="yes" else 0 for _, x in acceptance_results[target_model_a].items()]) / len(acceptance_results[target_model_a]),
        f"{target_model_b}": sum([1 if x[0]=="yes" else 0 for _, x in acceptance_results[target_model_b].items()]) / len(acceptance_results[target_model_b]),
        "agreement": agreement_results,
    }


def get_comparison_results(records, target_model_a, target_model_b):
    comparison_results = {}
    for record in records:
        instance_id = record.instance_id
        model_a = record.model_a
        model_b = record.model_b
        if instance_id not in comparison_results:
            comparison_results[instance_id] = []

        if record.preference == "a-is-better":
            comparison_results[instance_id].append(f"{model_a} is clearly better")
        elif record.preference == "a-is-slightly-better":
            comparison_results[instance_id].append(f"{model_a} is slightly better")
        elif record.preference == "b-is-better":
            comparison_results[instance_id].append(f"{model_b} is clearly better")
        elif record.preference == "b-is-slightly-better":
            comparison_results[instance_id].append(f"{model_b} is slightly better")
        elif record.preference == "tie":
            comparison_results[instance_id].append("tie")
        else:
            print("-------------------------------------")
            print("Unknown preference value.")
            print(record)

    # thre can be multiple annotations for each instance; use the first comparison result for each instance
    earlies_comparison_results = [results[0] for _, results in comparison_results.items()]
    model_wins_counter = Counter(earlies_comparison_results)
    model_wins_rates = {
        result: count / len(earlies_comparison_results) for result, count in model_wins_counter.items()
    }
    # merge the clearly better and slightly better results
    model_wins_rates[f"{target_model_a}_wins"] = \
        sum([v for k, v in model_wins_rates.items() if target_model_a in k])
    model_wins_rates[f"{target_model_b}_wins"] = \
        sum([v for k, v in model_wins_rates.items() if target_model_b in k])

    # count how many instances get multiple annotations
    instances_with_multiple_annotations = [instance_id for instance_id, results in comparison_results.items() if len(results) > 1]
    agreement_results = {
        "num_instances_with_multiple_annotations": len(instances_with_multiple_annotations),
        "comparison_agreement": None,
        "relexed_comparison_agreement": None,
    }
    if instances_with_multiple_annotations:
        agreed_comparison = 0
        relexed_agreed_comparison = 0
        for instance_id in instances_with_multiple_annotations:
            simplified_comparisons = []
            for comparison_result in comparison_results[instance_id]:
                if comparison_result == "tie":
                    simplified_comparisons.append("tie")
                elif target_model_a in comparison_result:
                    simplified_comparisons.append(target_model_a)
                elif target_model_b in comparison_result:
                    simplified_comparisons.append(target_model_b)
                else:
                    print("Unknown comparison result.")
                    print(comparison_result)
            if len(set(simplified_comparisons[:2])) == 1:
                agreed_comparison += 1
                relexed_agreed_comparison += 1
            else:
                if "tie" in simplified_comparisons[:2]:
                    relexed_agreed_comparison += 0.5
        agreement_results["comparison_agreement"] = agreed_comparison / len(instances_with_multiple_annotations)
        agreement_results["relexed_comparison_agreement"] = relexed_agreed_comparison / len(instances_with_multiple_annotations)

    model_wins_rates["agreement"] = agreement_results
    return model_wins_rates

def summarize_results(in_path, out_path):
    annotations = pd.read_excel(in_path, header=0)

    num_anns = len(annotations)
    num_evals = len(set(annotations["evaluator"].tolist()))

    print("Num of annotations: {}".format(num_anns))
    print("Num of evaluators: {}".format(num_evals))

    instance_annotators = {}
    for record in annotations.iterrows():
        instance_index = record[1]["instance_index"]
        if instance_index not in instance_annotators:
            instance_annotators[instance_index] = []
        annotator = record[1]["evaluator"]
        instance_annotators[instance_index].append(annotator)

    instance_records = {}
    for record in annotations.iterrows():
        instance_index = record[1]["instance_index"]
        if instance_index not in instance_records:
            instance_records[instance_index] = []
        instance_records[instance_index].append(record[1])

    # remove the duplicate records from the same evaluator
    print("Removing duplicate records from the same evaluator...")
    for instance_index, records in instance_records.items():
        # sort the records by timestamp descendingly, this way the latest record will be kept
        records = sorted(records, key=lambda x: x["timestamp"], reverse=True)
        evaluators = set()
        new_records = []
        for record in records:
            if record["evaluator"] not in evaluators:
                evaluators.add(record["evaluator"])
                new_records.append(record)
            else:
                print("duplicate record for instance {} by evaluator {}".format(instance_index, record["evaluator"]))
        instance_records[instance_index] = new_records
    deduplicated_records = []
    for instance_index, records in instance_records.items():
        for record in records:
            deduplicated_records.append(record)

    # resort the records by timestamp ascendingly
    deduplicated_records = sorted(deduplicated_records, key=lambda x: x["timestamp"])
    print("Num of deduplicated records: {}".format(len(deduplicated_records)))

    model_pairs = set()
    for record in deduplicated_records:
        model_pair = tuple(sorted([record["model_a"], record["model_b"]]))
        model_pairs.add(model_pair)
    print("Model pairs:")
    for model_pair in model_pairs:
        print(f"{model_pair[0]} vs {model_pair[1]}")

    results = {}
    for target_model_a, target_model_b in model_pairs:
        comparison_records = []
        for record in deduplicated_records:
            # instance id is used to identify the comparison instance
            # there could be multiple records for the same instance
            # instance_id = record.instance_id

            # skip if the record is not for the target model pair
            if set([target_model_a, target_model_b]) != set([record.model_a, record.model_b]):
                assert any([set([record.model_a, record.model_b]) == set(pair) for pair in model_pairs])
                continue

            comparison_records.append(record)

        acceptance_results = get_acceptance_results(comparison_records, target_model_a, target_model_b)
        comparison_results = get_comparison_results(comparison_records, target_model_a, target_model_b)
        results[f"{target_model_a}_vs_{target_model_b}"] = {
            "acceptance_results": acceptance_results,
            "comparison_results": comparison_results,
        }

    print("Results:")
    for model_pair, result in results.items():
        print(model_pair)
        print(json.dumps(result, indent=4))

    with open(out_path, "w") as f:
        json.dump(results, f, indent=4)

    return results, num_anns, num_evals


def plot_acceptance(results, out_path, num_anns, num_evals):
    """Plot the results and save to out_path."""
    # Plot acceptance rates
    acceptance_data = []
    for model_pair, result in results.items():
        acceptance_data.append({
            "model_pair": model_pair,
            "model": list(result["acceptance_results"].keys())[0],
            "acceptance_rate": result["acceptance_results"][list(result["acceptance_results"].keys())[0]],
        })
        acceptance_data.append({
            "model_pair": model_pair,
            "model": list(result["acceptance_results"].keys())[1],
            "acceptance_rate": result["acceptance_results"][list(result["acceptance_results"].keys())[1]],
        })
    acceptance_df = pd.DataFrame(acceptance_data)

    plt.figure(figsize=(10, 6))
    colors = ['r', 'y']
    ax = plt.subplot(111)
    for _, model_pair in enumerate(acceptance_df["model_pair"].unique()):
        subset = acceptance_df[acceptance_df["model_pair"] == model_pair]
        p = ax.bar(subset["model"], subset["acceptance_rate"], label=model_pair, color=colors)
        ax.bar_label(p, label_type='center')
    plt.ylabel("Acceptance Rate")
    plt.title("Model Acceptance Rates ({} Judgements by {} Evaluators)".format(num_anns, num_evals))
    plt.ylim(0, 1.15)
    plt.legend(handles=[],
               title='IAA -- ' + ", ".join(
                   [f"{model_pair}: {results[model_pair]['acceptance_results']['agreement']['acceptance_agreement']:.2f}" for model_pair in results.keys()]
                   ), 
               loc='upper center')
    plt.xticks(rotation=90)
    plt.savefig(f"{out_path}_acceptance_rates.png",  bbox_inches='tight')
    plt.close()


def plot_comparison(results, out_path, num_anns, num_evals):
    """Plot the results and save to out_path."""
    # Plot acceptance rates
    comparison_data = []
    for model_pair, result in results.items():
        comparison_data.append({
            "model_pair": model_pair,
            "model": list(result["comparison_results"].keys())[0],
            "preference": result["comparison_results"][list(result["comparison_results"].keys())[0]],
        })
        comparison_data.append({
            "model_pair": model_pair,
            "model": list(result["comparison_results"].keys())[1],
            "preference": result["comparison_results"][list(result["comparison_results"].keys())[1]],
        })
        comparison_data.append({
            "model_pair": model_pair,
            "model": list(result["comparison_results"].keys())[2],
            "preference": result["comparison_results"][list(result["comparison_results"].keys())[2]],
        })
        comparison_data.append({
            "model_pair": model_pair,
            "model": list(result["comparison_results"].keys())[3],
            "preference": result["comparison_results"][list(result["comparison_results"].keys())[3]],
        })
        comparison_data.append({
            "model_pair": model_pair,
            "model": list(result["comparison_results"].keys())[4],
            "preference": result["comparison_results"][list(result["comparison_results"].keys())[4]],
        })
    comparison_df = pd.DataFrame(comparison_data)

    plt.figure(figsize=(10, 6))
    colors = ['r', 'y', 'g', 'c', 'm']
    ax = plt.subplot(111)
    for _, model_pair in enumerate(comparison_df["model_pair"].unique()):
        subset = comparison_df[comparison_df["model_pair"] == model_pair]
        p = ax.bar(subset["model"], subset["preference"], label=model_pair, color=colors)
        ax.bar_label(p, label_type='center')
    plt.ylabel("Preference Rate")
    plt.title("Model Preferences ({} Judgements by {} Evaluators)".format(num_anns, num_evals))
    plt.ylim(0, 1.15)
    plt.legend(handles=[],
        title="Relaxed IAA -- " + ", ".join(
            [f"{model_pair}: {results[model_pair]['comparison_results']['agreement']['relexed_comparison_agreement']:.2f}" for model_pair in results.keys()]
            ), 
        loc='upper center')
    plt.xticks(rotation=90)
    plt.savefig(f"{out_path}_comparison_preferences.png",  bbox_inches='tight')
    plt.close()


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Load results Excel sheet and compute IAA metrics."
    )

    parser.add_argument(
        "file",
        help="Path to the exported annotations file (Excel .xlsx sheet)"
    )

    args = parser.parse_args()

    results, num_anns, num_evals = summarize_results(args.file, args.file.replace('.xlsx', '_results.json'))
    plot_acceptance(results, args.file.replace('.xlsx', ''), num_anns=num_anns, num_evals=num_evals)
    plot_comparison(results, args.file.replace('.xlsx', ''), num_anns=num_anns, num_evals=num_evals)