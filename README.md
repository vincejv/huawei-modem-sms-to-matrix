# Huawei Modem SMS to Matrix Bridge

Sends SMS messages from Huawei modem to Matrix chatrooms through the Matrix API

Tested to work on
- Huawei H153-381
- Huawei H155-382

To run:
1. Install postgres 
2. Create a database in postgres
3. Run the statements in `db.sql` in postgres to init database
4. Use the example `docker-compose.yml`
5. Adjust the environment variables
6. `docker-compose up -d`

Roadmap:
- Add sending of SMS through Matrix API/Bot
- More documentation