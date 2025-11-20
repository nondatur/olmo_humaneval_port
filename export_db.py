import sqlite3, argparse

import pandas as pd

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Export an Excel sheet from the evaluation `data/evaluation.db` database to selected path."
    )

    parser.add_argument(
        "file_path",
        help="Path to the exported Excel file (.xlsx)"
    )

    # database connection
    DATABASE = "data/evaluation.db"
    DB_CONN = sqlite3.connect(DATABASE, check_same_thread=False)
    DB_CURSOR = DB_CONN.cursor()


    # export the evaluation results as excel
    args = parser.parse_args()
    evaluation_results = pd.read_sql_query("SELECT * from evaluation_record", DB_CONN)
    evaluation_results.to_excel(args.file_path, index=False)
