import json
import csv
import os
import json
import tempfile
import shutil
import requests
from datetime import datetime, timedelta
from pysqlcipher3 import dbapi2 as sqlite


def convert_timestamp(timestamp: int):
    timestamp = timestamp / 1000  # Divide by 1000 to convert milliseconds to seconds
    date = datetime.fromtimestamp(timestamp).strftime("%Y/%m/%d %H:%M")
    return date


def extract_signal_db(output_dir: os.PathLike):
    # Path to the Signal database file
    db_path = os.path.expanduser("~/.config/Signal/sql/db.sqlite")

    # Path to the Signal config file
    config_path = os.path.expanduser("~/.config/Signal/config.json")

    # Get the decryption key from the Signal config file
    with open(config_path) as config_file:
        config_data = json.load(config_file)
        decryption_key = config_data["key"]

    # Connect to the encrypted database using SQLCipher
    conn = sqlite.connect(db_path)

    cursor = conn.cursor()
    cursor.execute(f"PRAGMA key =\"x'{decryption_key}'\";")
    cursor.execute("PRAGMA cipher_compatibility = 4")

    # Define a function to handle the fallback logic
    def get_profile_name(row):
        if "profileName" in row and row["profileName"] is not None:
            return row["profileName"]
        elif "profileFullName" in row and row["profileFullName"] is not None:
            return row["profileFullName"]
        else:
            return None

    # Load the conversations table and create the dictionary of names
    profile_dict = {}
    cursor.execute("SELECT * FROM conversations")
    for r in cursor.fetchall():
        row = json.loads(r[1])
        if "uuid" not in row:
            continue
        uuid = row["uuid"]
        profile_name = get_profile_name(row)
        profile_dict[uuid] = profile_name

    # Get the current timestamp and calculate the timestamp for four weeks ago
    current_timestamp = int(datetime.now().timestamp()) * 1000
    four_weeks_ago = int((datetime.now() - timedelta(weeks=4)).timestamp()) * 1000

    # SQL query to select the relevant messages
    sql_query = f"""
        SELECT sent_at, sourceUuid, type, body
        FROM messages
        WHERE (sent_at > {four_weeks_ago} AND sent_at < {current_timestamp})
        AND conversationId = ?
    """

    # Execute the query for each conversation
    cursor.execute("SELECT id FROM conversations")

    output_files = []
    for row in cursor.fetchall():
        conversation_id = row[0]

        # Fetch the messages for the current conversation
        #
        print(conversation_id)
        cursor.execute(sql_query, (conversation_id,))
        messages = cursor.fetchall()

        # Skip conversations with no messages in the last four weeks
        if len(messages) == 0:
            continue

        # Replace sourceUuid with names from profile_dict
        messages = [
            (convert_timestamp(sent_at), profile_dict.get(uuid, uuid), body)
            for sent_at, uuid, _, body in messages
        ]

        # Create the output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Create a CSV file for the conversation
        output_file = f"conversation_{conversation_id}.csv"
        output_files += output_file
        output_path = os.path.join(output_dir, output_file)
        with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["sent_at", "user", "body"])  # Write the header row
            writer.writerows(messages)  # Write the messages to the CSV file

    # Close the database connection
    cursor.close()
    conn.close()
    return output_files


def compress_convo(convo_file, output_dir):
    current_timestamp = int(datetime.now().timestamp()) * 1000
    # process the conversion
    output_file = os.path.join(output_dir, convo_file)

    with open(output_file, "r") as file:
        data = file.read()

    data += """\n\n\n

    The above is a CSV formatted chat log of a group chat conversation over the past 4 weeks.
    Summarize what happened, without including specific messages or timestamps.

    E.g., "person X said this, this topic was discussed on Thursday the 12th, etc"\n

    Summary:
    """
    port = "9090"
    service = "llama"
    url = f"http://{service}:{port}/completion"
    headers = {"Content-Type": "application/json"}
    payload = {
        "prompt": data,
        "n_predict": 1024,
    }

    response = requests.post(url, headers=headers, json=payload)
    response_text = response.text

    # Create the output directory if it doesn't exist
    final_output_dir = "/output"
    os.makedirs(final_output_dir, exist_ok=True)

    # Define the path for the output file
    output_file_path = os.path.join(
        final_output_dir, f"output_{convo_file}_{current_timestamp}.txt"
    )

    # Write the response data to the output file
    with open(output_file_path, "w") as file:
        file.write(response_text)

    print(f"Response data dumped to {output_file_path}")

    response = requests.post(url, headers=headers, json=data)
    print(response.text)


if __name__ == "__main__":
    output_dir = tempfile.mkdtemp()  # Output directory for CSV files

    output_files = extract_signal_db(output_dir)
    convo_file = "conversation_85ae4e9e-13e5-40f8-aeb0-1369c9fa22ec.csv"
    compress_convo(convo_file, output_dir)

    for f in output_files:
        if "aeb0-" not in convo_file:
            compress_convo(f, output_dir)
    # delete temporary files
    shutil.rmtree(output_dir)
