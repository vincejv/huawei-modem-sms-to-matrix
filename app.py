import huaweisms.api.user
import huaweisms.api.sms
import psycopg2
import requests
from datetime import datetime
import time
import os

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

# Connect to PostgreSQL database
def get_last_message():
    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    cur.execute("SELECT date, index FROM last_message WHERE id = 1;")
    last_message_row = cur.fetchone()
    last_date = last_message_row[0] if last_message_row else datetime.min
    last_index = last_message_row[1] if last_message_row else -1
    cur.close()
    conn.close()
    return last_date, last_index

def update_last_message(new_last_date, new_last_index):
    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    cur.execute("UPDATE last_message SET date = %s, index = %s WHERE id = 1;", (new_last_date, new_last_index))
    conn.commit()
    cur.close()
    conn.close()

# Send message to Matrix Synapse API
def send_to_matrix(phone, date, content):
    print(f"Sending to matrix: {phone} | {content}")
    message_body = {
        "msgtype": "m.text",
        "body": f"From: {phone}\nDate: {date}\n---\n{content}"
    }
    api_url = MATRIX_API_URL.format(roomId=ROOM_ID, token=ACCESS_TOKEN)
    response = requests.post(api_url, json=message_body)
    if response.status_code != 200:
        print(f"Failed to send message to Matrix Synapse: {response.content}")

# Poll for new messages in an infinite loop
def poll_messages():
    while True:
        # print("Polling...")
        # Log in to the modem
        ctx = huaweisms.api.user.quick_login(USERNAME, PASSWORD, modem_host=MODEM_HOST)

        # Get the last message date and index from the database
        last_date, last_index = get_last_message()

        page = 1
        messages_per_page = 10
        new_messages = []

        while True:
            sms_response = huaweisms.api.sms.get_sms(ctx, page=page, qty=messages_per_page, box_type=1)
            if sms_response.get('type') == 'response' and int(sms_response['response'].get('Count')) > 0:
                messages = sms_response['response']['Messages'].get('Message', [])

                if isinstance(messages, dict):
                    messages = [messages]

                for message in messages:
                    message_date = datetime.strptime(message['Date'], "%Y-%m-%d %H:%M:%S")
                    message_index = int(message['Index'])

                    # Compare both date and index for uniqueness
                    if (message_date > last_date) or (message_date == last_date and message_index > last_index):
                        # new message found
                        new_messages.append(message)
                        huaweisms.api.sms.delete_sms(ctx, message_index)

                if len(messages) < messages_per_page:
                    break

                page += 1
            else:
                break

        # Sort new messages by date before processing
        if new_messages:
            new_messages.sort(key=lambda m: (datetime.strptime(m['Date'], "%Y-%m-%d %H:%M:%S"), int(m['Index'])))

            # Process and send new messages
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

        # Log out from the modem
        huaweisms.api.user.logout(ctx)

        # Wait for a minute before polling again
        time.sleep(MODEM_POLL_SEC)

if __name__ == "__main__":
    print("Starting SMS Polling application...")
    poll_messages()
