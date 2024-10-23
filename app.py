import logging
from huawei_lte_api.Connection import Connection
from huawei_lte_api.Client import Client
from huawei_lte_api.enums.client import ResponseEnum
import psycopg2
import requests
from datetime import datetime
import time
import os

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Replace with your modem's admin username and password
USERNAME = os.environ.get('MODEM_USERNAME', 'pldthome')
PASSWORD = os.environ.get('MODEM_PASSWORD', 'pldthome')
MODEM_HOST = os.environ.get('MODEM_HOST', '192.168.1.1') # only ip addresses are allowed for now
MODEM_POLL_SEC = int(os.environ.get('POLL_SEC', '10'))

# PostgreSQL credentials
DB_HOST = os.environ['DB_HOST']
DB_NAME = os.environ['DB_NAME']
DB_USER = os.environ['DB_USER']
DB_PASS = os.environ['DB_PASS']

# Matrix Synapse API details
ROOM_ID = os.environ['ROOM_ID']
ACCESS_TOKEN = os.environ['ACCESS_TOKEN']
MATRIX_HOST = os.environ['MATRIX_HOST']
MATRIX_API_URL = f"https://{MATRIX_HOST}/_matrix/client/r0/rooms/{ROOM_ID}/send/m.room.message?access_token={ACCESS_TOKEN}"

# Truncation
MAX_LENGTH = 73
ELLIPSIS = "..."

# Connect to PostgreSQL database
def get_last_message(id=1):
    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    cur.execute("SELECT date, index FROM last_message WHERE id = %s;", (id,))
    last_message_row = cur.fetchone()
    last_date = last_message_row[0] if last_message_row else datetime.min
    last_index = last_message_row[1] if last_message_row else -1
    cur.close()
    conn.close()
    return last_date, last_index

def update_last_message(new_last_date, new_last_index, id=1):
    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    cur.execute("UPDATE last_message SET date = %s, index = %s WHERE id = %s;", (new_last_date, new_last_index, id))
    conn.commit()
    cur.close()
    conn.close()

# Send message to Matrix Synapse API
def send_to_matrix(phone, date, content):
    truncated_content = truncate_and_replace(content)
    logging.info(f"Sending to matrix: {phone} | {truncated_content}")
    message_body = {
        "msgtype": "m.text",
        "body": f"From: {phone}\nDate: {date}\n---\n{content}"
    }
    api_url = MATRIX_API_URL.format(roomId=ROOM_ID, token=ACCESS_TOKEN)
    response = requests.post(api_url, json=message_body)
    if response.status_code != 200:
        logging.error(f"Failed to send message to Matrix Synapse: {response.content}")

def truncate_and_replace(text):
    # Replace newlines with spaces
    text = text.replace('\n', ' ')
    
    # Truncate to (MAX_LENGTH - len(ELLIPSIS)) and add ellipsis if needed
    return (text[:MAX_LENGTH - len(ELLIPSIS)] + ELLIPSIS) if len(text) > MAX_LENGTH else text

# Poll for new messages in an infinite loop
def poll_messages():
    # Log in to the modem
    with Connection(f'http://{MODEM_HOST}/', username=USERNAME, password=PASSWORD) as connection:
        client = Client(connection)
        while True:
            logging.debug(f"Polling modem every {MODEM_POLL_SEC}s")

            # Get the last message date and index from the database
            last_date, last_index = get_last_message(1)

            new_messages = []
            page = 1  # Start with the first page

            # Loop until all pages are fetched
            while True:
                sms_data = {}
                sms_data = client.sms.get_sms_list(page=page, ascending=True)  # 1 = inbox

                if 'Messages' not in sms_data or sms_data['Count'] == '0':
                    break  # Stop when there are no more messages

                # Extract messages
                messages = sms_data['Messages']['Message'] if isinstance(sms_data['Messages']['Message'], list) else [sms_data['Messages']['Message']]

                for message in messages:
                    message_date = datetime.strptime(message['Date'], "%Y-%m-%d %H:%M:%S")
                    message_index = int(message['Index'])

                    # Compare both date and index for uniqueness
                    if (message_date > last_date) or (message_date == last_date and message_index > last_index):
                        new_messages.append(message)
                        client.sms.delete_sms(message_index)

                # Stop fetching if Count is 0 or less messages
                if sms_data['Count'] == '0' or len(messages) < 20:  # Assuming each page fetches 20 messages
                    break

                page += 1  # Go to the next page if there are more messages

            # Process and send new messages
            if new_messages:
                for message in new_messages:
                    phone = message.get('Phone', 'Unknown')
                    date = message.get('Date', 'Unknown')
                    content = message.get('Content', 'No content')

                    # Send to Matrix Synapse API
                    send_to_matrix(phone, date, content)

                # Update last date and index with the latest message
                last_message = max(new_messages, key=lambda m: (datetime.strptime(m['Date'], "%Y-%m-%d %H:%M:%S"), int(m['Index'])))
                last_message_date = datetime.strptime(last_message['Date'], "%Y-%m-%d %H:%M:%S")
                last_message_index = int(last_message['Index'])

                update_last_message(last_message_date, last_message_index)

            # Poll and process call logs
            last_call_date, _ = get_last_message(2)
            log_lines = [line for line in client.log.loginfo().get('LogContent').split('\\r\\n') if "call:" in line][:15]  # Get the last 15 log lines
            new_call_logs = []

            for log in log_lines:
                parts = log.split('User Notice ')
                if len(parts) > 1:
                    log_info = parts[1].strip()
                    call_type = log_info.split(':')[0]  # Get the call type (Missed call or Outgoing call)

                    # Extract relevant information
                    details = log_info.split(', ')
                    call_info = {}
                    for detail in details:
                        key, value = detail.split(':', 1)
                        call_info[key.strip()] = value.strip()

                    # Get call details
                    caller = call_info.get('Caller', 'Unknown')
                    callee = call_info.get('Callee', 'Unknown')
                    duration = call_info.get('Duration', '00:00:00')
                    log_time = datetime.strptime(log[:19], "%Y-%m-%d %H:%M:%S")  # Extract the timestamp from the log

                    # Check if the call log is new before inserting
                    if log_time > last_call_date:
                        new_call_logs.append({
                            'log_time': log_time,
                            'call_type': call_type,
                            'callee': callee,
                            'caller': caller,
                            'duration': duration
                        })

            # Update last call log time with the most recent timestamp
            if new_call_logs:
                for call in new_call_logs:
                    # Send the call log to Matrix
                    trigger_from = call['call_type']  # Assuming caller as the phone number
                    call_date = call['log_time'].strftime("%Y-%m-%d %H:%M:%S")
                    matrix_content = f"Caller: {call['caller']}\nCallee: {call['callee']}\nDuration: {call['duration']}"

                    # Send to Matrix Synapse API
                    send_to_matrix(trigger_from, call_date, matrix_content)
                
                latest_call_log_time = max(call['log_time'] for call in new_call_logs)  # Update with the latest timestamp
                update_last_message(latest_call_log_time, -1, 2)
            
            logging.debug("Finished polling for now, waiting for the next cycle.")
            time.sleep(MODEM_POLL_SEC)

if __name__ == "__main__":
    logging.info("Starting the SMS and Call poller")
    # Print the variables at startup
    logging.info(f"MODEM_USERNAME: {USERNAME}")
    logging.info(f"MODEM_HOST: {MODEM_HOST}")
    logging.info(f"MODEM_POLL_SEC: {MODEM_POLL_SEC}")
    logging.info(f"DB_HOST: {DB_HOST}")
    logging.info(f"DB_NAME: {DB_NAME}")
    logging.info(f"DB_USER: {DB_USER}")
    logging.info(f"DB_PASS: {'*' * len(DB_PASS)}")  # Masked password
    logging.info(f"ROOM_ID: {ROOM_ID}")
    logging.info(f"MATRIX_HOST: {MATRIX_HOST}")
    logging.info(f"ACCESS_TOKEN: {'*' * len(PASSWORD)}")  # Masked password
    poll_messages()
    logging.warning("Cookie expired or login failed, program is terminating...")
