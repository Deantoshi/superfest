import pandas as pd
import requests
from datetime import datetime as dt, date, timezone
import time
from pandas import json_normalize
import numpy as np
import json
from cloud_storage import cloud_storage as cs
from flask import Flask, send_from_directory, send_file, make_response, jsonify, url_for, Response, stream_with_context
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from google.cloud import storage
from google.cloud.exceptions import NotFound
from google.auth import default
from google.oauth2 import service_account
import pandas as pd
import io
from io import BytesIO
import logging
import time
import zipfile
import csv
from functools import lru_cache
from typing import List, Dict

COOLDOWN_TIME = 5
START_DATE = '2024-07-08'
PRICE_BLOCKCHAIN = 'optimism'
OPTIMISM_TOKEN_ADDRESS = '0x4200000000000000000000000000000000000042'
WETH_TOKEN_ADDRESS = '0x4200000000000000000000000000000000000006'

CLOUD_BUCKET_NAME = 'cooldowns2'
CLOUD_PRICE_FILENAME = 'token_prices.zip'
CLOUD_DATA_FILENAME = 'super_fest.zip'
CLOUD_AGGREGATE_FILENAME = 'super_fest_aggregate.zip'

# logging.basicConfig(level=logging.DEBUG)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
cors = CORS(app, origins='*')
# CORS(app, resources={r"/api/*": {"origins": "https://superfest-frontend-dot-internal-website-427620.uc.r.appspot.com"}})

# Initialize GCP storage client
# credentials, project = default()
# storage_client = storage.Client(credentials=credentials, project=project)

# Initialize the rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
limiter.init_app(app)

def get_protocol_pool_config_df():

    df = pd.read_csv('protocol_pool.csv')

    return df

# # given a pool id, returns it's historic tvl and yield
def get_historic_protocol_pool_tvl_and_yield(pool_id):
    
    url = "https://yields.llama.fi/chart/" + pool_id

    # Send a GET request to the URL
    response = requests.get(url)

    # Check if the request was successful
    if response.status_code == 200:
        # Request was successful
        data = response.json()  # Parse the JSON response
    else:
        # Request failed
        print(f"Request failed with status code: {response.status_code}")
        print(response.text)  # Print the response content for more info on the error

    return data


def get_historic_protocol_tvl_json(protocol_slug):
    url = "https://api.llama.fi/protocol/" + protocol_slug

    # Send a GET request to the URL
    response = requests.get(url)

    # Check if the request was successful
    if response.status_code == 200:
        # Request was successful
        data = response.json()  # Parse the JSON response
    else:
        # Request failed
        print(f"Request failed with status code: {response.status_code}")
        print(response.text)  # Print the response content for more info on the error

    return data

# # does our DefiLlama API call for dex tvl history
def get_historic_dex_tvl_json(pool_id):

    url = "https://yields.llama.fi/chart/" + pool_id

    # Send a GET request to the URL
    response = requests.get(url)

    # Check if the request was successful
    if response.status_code == 200:
        # Request was successful
        data = response.json()  # Parse the JSON response
    else:
        # Request failed
        print(f"Request failed with status code: {response.status_code}")
        print(response.text)  # Print the response content for more info on the error

    return data


# # makes a dataframe for our usd_supplied amounts
def get_historic_protocol_tvl_df(data, blockchain, category):
    # Extract the tokensInUsd list
    tokens_in_usd = data['chainTvls'][blockchain][category]
    # tokens_in_usd = data['chainTvls'][blockchain]['tokensInUsd']

    if len(tokens_in_usd) < 1:
        tokens_in_usd = data['chainTvls'][blockchain]['tokens']

    # Create a list of dictionaries with the correct structure
    formatted_data = [
        {
            'date': entry['date'],
            **entry['tokens']  # Unpack the tokens dictionary
        }
        for entry in tokens_in_usd
    ]

    # Create DataFrame directly from the formatted data
    df = pd.DataFrame(formatted_data)

    # Ensure 'date' is the first column
    columns = ['date'] + [col for col in df.columns if col != 'date']
    df = df[columns]

    # Sort the DataFrame by date
    df = df.sort_values('date')

    # Reset the index to have a standard numeric index
    df = df.reset_index(drop=True)

    df.rename(columns = {'date':'timestamp'}, inplace = True)

    # df['timestamp'] = pd.to_datetime(df['timestamp'])

    return df

# # makes a dataframe for our usd_supplied amounts
def get_historic_dex_tvl_df(data):
    df = pd.DataFrame()

    # Check if the input is a string (JSON) or a dictionary
    if isinstance(data, str):
        # If it's a string, parse it as JSON
        data = json.loads(data)
    
    # Extract the list of data points
    try:
        data_points = data['data']
   
    # # except we will iterate through the data to make it df compliant
    except:
        all_data = []
    
        for chain, data in data['chainTvls'].items():
            if 'tvl' in data:
                for entry in data['tvl']:
                    row = {
                        'chain': chain,
                        # 'timestamp': dt.fromtimestamp(entry['date']).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                        'timestamp': int(entry['date']),
                        'tvl': entry['totalLiquidityUSD']
                    }
                    all_data.append(row)
    
        # Create DataFrame
        df = pd.DataFrame(all_data)
        # Sort by date and chain
        df = df.sort_values(['timestamp', 'chain'])
        df = df.loc[df['chain'] != 'borrowed']

    
    # Create DataFrame directly from the data points
    if len(df) < 1:
        df = pd.DataFrame(data_points)
    
    # Convert timestamp to datetime
    try:
        df['timestamp'] = df['timestamp'].apply(lambda x: int(dt.strptime(x, '%Y-%m-%dT%H:%M:%S.%fZ').timestamp()))
    except:
        pass
    
    # Sort the DataFrame by timestamp
    df = df.sort_values('timestamp')
    
    # Reset the index to have a standard numeric index
    df = df.reset_index(drop=True)
    
    df.to_csv('test_test.csv',index=False)

    return df

# # simply turns our dataframe into a df adn goes ahead and casts our timestamp into a datetime data type
def turn_json_into_df(data):

    df = pd.DataFrame(data['data'])
    # Convert timestamp to datetime
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['tvlUsd'] = df['tvlUsd'].astype('float')

    df = df[['timestamp', 'tvlUsd', 'apy']]

    return df

def get_utc_start_day():
    # Create a datetime object for July 7th, 2024, at 00:00:00 UTC
    date = dt(2024, 7, 10, 0, 0, 0, tzinfo=timezone.utc)

    return date

# # date string into unix timestamp
def date_to_unix_timestamp(date_string, format="%Y-%m-%d"):
    # Convert string to datetime object
    date_object = dt.strptime(date_string, format)
    
    # Convert datetime object to Unix timestamp
    unix_timestamp = int(time.mktime(date_object.timetuple()))
    
    return unix_timestamp


# # only returns items that are greater than a certain day
def filter_start_timestamp(df, start_day):

    df['timestamp'] = df['timestamp'].astype(float)

    df = df.loc[df['timestamp'] >= start_day]
    
    df.to_csv('test_test.csv',index=False)

    return df

# # gives the tvl at the beginning of our tracking
def get_start_tvl(df):

    temp_df = df.loc[df['timestamp'] == df['timestamp'].min()]

    start_tvl = temp_df['tvlUsd'].min()

    df['start_tvl'] = start_tvl

    return df

def get_tvl_change_since_start(df):

    df['change_in_tvl'] = df['tvlUsd'] - df['start_tvl']

    return df

def run_all_apy():

    pool_df = get_protocol_pool_config_df()

    pool_id_list = pool_df['pool_id'].unique()

    df_list = []

    for pool_id in pool_id_list:

        data = get_historic_protocol_pool_tvl_and_yield(pool_id)
        df = turn_json_into_df(data)
        start_day = get_utc_start_day()
        df = filter_start_timestamp(df, start_day)
        df = get_start_tvl(df)
        df.to_csv('test_test.csv',index=False)
        df = get_tvl_change_since_start(df)
        df_list.append(df)
    
    df = pd.concat(df_list)

    return df


# # will manage pinging our api for us and making a subsequent df
def get_pool_type_df(data, protocol_blockchain, pool_type):

    df = pd.DataFrame()

    # # if it is a supply pool, then we make sure to add borrows to it to get a better total market size
    if pool_type == 'supply':
        category = 'tokensInUsd'
        
        try:
            df = get_historic_protocol_tvl_df(data, protocol_blockchain, category)
        except:
            df = get_historic_dex_tvl_df(data)

        try:
            pool_type = 'borrow'
            protocol_blockchain += '-borrowed'
            borrow_df = get_historic_protocol_tvl_df(data, protocol_blockchain, category)

            df = add_dataframes(df, borrow_df)
        except:
            print('could not add supply and borrow dataframes')


    elif pool_type == 'borrow':
        category = 'tokensInUsd'
        protocol_blockchain += '-borrowed'
        df = get_historic_protocol_tvl_df(data, protocol_blockchain, category)
    

    elif pool_type == 'AMM' or pool_type == 'Yield_Vault' or pool_type == 'Lending':
        # if pool_type == 'Yield_Vault':
        #     print('Yield')
    
        category = 'tokensInUsd'
        df = get_historic_dex_tvl_df(data)

    return df

# # divides our dataframe columns to essentially find the token prices
def divide_dataframes(df_top, df_bottom):
    # Ensure both dataframes have the same index
    df_top = df_top.set_index('timestamp')
    df_bottom = df_bottom.set_index('timestamp')

    # List of token columns (excluding 'timestamp' and 'pool_type')
    token_columns = [col for col in df_bottom.columns if col not in ['timestamp', 'pool_type']]

    # Perform element-wise division
    result = df_top[token_columns] / df_bottom[token_columns]

    # Reset the index to make 'timestamp' a column again
    result = result.reset_index()

    return result

# # adds our two dataframes together
def add_dataframes(df1, df2):
    # Ensure both dataframes have the same index
    df1 = df1.set_index('timestamp')
    df2 = df2.set_index('timestamp')

    # Get all unique columns from both dataframes
    all_columns = list(set(df1.columns) | set(df2.columns))

    # Fill missing columns with 0
    df1 = df1.reindex(columns=all_columns, fill_value=0)
    df2 = df2.reindex(columns=all_columns, fill_value=0)

    # Add the dataframes
    result = df1.add(df2, fill_value=0)

    # Reset the index to make 'timestamp' a column again
    result = result.reset_index()

    return result

# def add_dataframes(df1, df2):
#     # Ensure both dataframes have the same index
#     df1 = df1.set_index('timestamp')
#     df2 = df2.set_index('timestamp')

#     # List of token columns (excluding 'timestamp')
#     token_columns = [col for col in df1.columns if col != 'timestamp']
#     token_columns_2 = [col for col in df2.columns if col != 'timestamp']

#     # # shared token columns
#     token_columns = list(set(token_columns) & set(token_columns_2))

#     df1 = df1[token_columns]
#     df2 = df2[token_columns]


#     # Add the dataframes
#     result = df1[token_columns].add(df2[token_columns], fill_value=0)

#     # Reset the index to make 'timestamp' a column again
#     result = result.reset_index()

#     return result

# # transposes our token columns
def transpose_df(df):
    token_columns = [col for col in df.columns if col not in ['timestamp', 'pool_type']]

    # Melt the DataFrame
    df_melted = pd.melt(df, 
                        id_vars=['timestamp', 'pool_type'],
                        value_vars=token_columns,
                        var_name='token',
                        value_name='token_amount')

    # Reorder columns
    df_melted = df_melted[['timestamp', 'token', 'token_amount', 'pool_type']]

    # Sort by timestamp and token
    df_melted = df_melted.sort_values(['timestamp', 'token'])

    # Reset index
    df_melted = df_melted.reset_index(drop=True)

    df = df_melted

    return df

# Define a function to get the first non-NaN value
def first_valid(series):
    return series.dropna().iloc[0] if not series.dropna().empty else np.nan

# # makes a new column for the starting_token_amount
def add_start_token_amount_column(df):

    # Create the start_token_amount column
    df['start_token_amount'] = df.groupby(['token', 'pool_type'])['token_amount'].transform(first_valid)

    # Fill NaN values with 0 in the entire DataFrame
    df = df.fillna(0)

    # Sort the DataFrame by timestamp, token, and pool_type for better readability
    df = df.sort_values(['timestamp', 'token', 'pool_type'])

    # Reset the index
    df = df.reset_index(drop=True)

    return df

def add_change_in_token_amounts(df):

    df[['token_amount', 'start_token_amount']] = df[['token_amount', 'start_token_amount']].astype(float)

    df['raw_change_in_usd'] = df['token_amount'] - df['start_token_amount']
    df['percentage_change_in_usd'] = (df['token_amount'] / df['start_token_amount'] - 1)

    df = df.loc[df['percentage_change_in_usd'] > -0.99]

    # Fill NaN values with 0 in the entire DataFrame
    df = df.fillna(0)

    return df

# # will return the price per token from usd amount / quantity amount
def find_token_prices(usd_df, data, protocol_blockchain):

    category = 'tokens'
    quantity_df = get_historic_protocol_tvl_df(data, protocol_blockchain, category)
    start_unix = int(date_to_unix_timestamp(START_DATE))

    quantity_df = filter_start_timestamp(quantity_df, start_unix)

    df = divide_dataframes(usd_df, quantity_df)

    return df

# # finds tvl over time for each asset supply and borrow side
def find_tvl_over_time(df):
    # Convert timestamp to datetime
    df['date'] = pd.to_datetime(df['timestamp'], unit='s').dt.date

    # Group by date and pool_type, then sum token_usd_amount
    grouped_df = df.groupby(['date', 'pool_type'])['token_usd_amount'].sum().reset_index()

    # Rename the token_usd_amount column to daily_tvl
    grouped_df = grouped_df.rename(columns={'token_usd_amount': 'daily_tvl'})

    # Merge the daily_tvl back to the original dataframe
    df = df.merge(grouped_df[['date', 'pool_type', 'daily_tvl']], on=['date', 'pool_type'], how='left')

    df = df[['timestamp', 'date', 'token', 'pool_type', 'token_usd_amount', 'start_token_usd_amount', 'raw_change_in_usd', 'percentage_change_in_usd', 'daily_tvl']]

    return df

# # will only return rows for tokens specified in our protocol_pool.csv file for our desired protocol
# # will onlry return pool_types that are specified in our protocol_pool.csv
# # then drops duplicate dates
def df_token_cleanup(protocol_df, df):

    unique_slugs = protocol_df['protocol_slug'].unique()

    df_list = []

    for unique_slug in unique_slugs:

        temp_config_df = protocol_df.loc[protocol_df['protocol_slug'] == unique_slug]

        unique_tokens = temp_config_df['token'].unique()

        for token in unique_tokens:
            temp_temp_config_df = temp_config_df.loc[temp_config_df['token'] == token]

            unique_pool_types = temp_temp_config_df['pool_type'].unique()

            for unique_pool in unique_pool_types:
                temp_df = df.loc[(df['protocol'] == unique_slug) & (df['token'] == token)  & (df['pool_type'] == unique_pool)]

                if len(temp_df) > 0:
                    df_list.append(temp_df)

    df = pd.concat(df_list)

    return df

# # gets our incentive history
def get_protocol_incentives_df():

    df = pd.read_csv('protocol_incentive_history.csv')
    return df

# Function to create new rows with incremented dates
def expand_rows(row):
    new_rows = [row.copy() for _ in range(7)]  # Create 7 copies (original + 6 new)
    for i in range(1, 7):
        new_rows[i]['date'] = row['date'] + pd.Timedelta(days=i)
    return pd.DataFrame(new_rows)

# # takes in a dataframe, and evenly distributes incentives accross the next 7 days
def fill_incentive_days(df):
    df['incentives_per_day'] = df['epoch_token_incentives'] / 7

    df['date'] = pd.to_datetime(df['date'])

    # Apply the function to each row and concatenate the results
    expanded_df = pd.concat([expand_rows(row) for _, row in df.iterrows()], ignore_index=True)

    # Sort the dataframe by date and other relevant columns if needed
    expanded_df = expanded_df.sort_values(['date', 'chain', 'platform', 'token', 'pool_type'])

    # Reset the index
    expanded_df = expanded_df.reset_index(drop=True)

    df = expanded_df
    
    return df

# # makes a unix timestamp column for our incentives
def get_incentives_unix_timestamps(df):
    df['timestamp'] = df['date'].apply(lambda x: pd.Timestamp(x).timestamp())

    df['timestamp'] = df['timestamp'].astype(int)
    return df

def make_dummy_cloud_price_df():

    df = pd.DataFrame()

    df['symbol'] = ['N/A']
    df['timestamp'] = [1776]
    df['date'] = ['2024-01-1']
    df['price'] = [1.5]
    df['token_address'] = ['N/A']

    return df

def parse_date(date_string):
    try:
        # Try parsing with microseconds
        return dt.strptime(str(date_string), '%Y-%m-%dT%H:%M:%S.%f').strftime('%Y-%m-%d')
    except ValueError:
        try:
            # If that fails, try parsing without microseconds
            return dt.strptime(str(date_string), '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d')
        except ValueError:
            # If both fail, return the original string
            return str(date_string)
        
# # will use the defillama price api to get the price of our token over time
# # returns a list of jsons
# # look here ** may need to remove the pricing functinoality that averages the two prices toghether
def get_token_price_json_list(df, blockchain, token_address):
    # url = "https://coins.llama.fi/batchHistorical?coins=%7B%22optimism:0x4200000000000000000000000000000000000042%22:%20%5B1666876743,%201666862343%5D%7D&searchWidth=600"
    # url = "https://coins.llama.fi/batchHistorical?coins=%7B%22optimism:0x4200000000000000000000000000000000000042%22:%20%5B1686876743,%201686862343%5D%7D&searchWidth=600"

    try:
        cloud_price_df = cs.read_zip_csv_from_cloud_storage(CLOUD_PRICE_FILENAME, CLOUD_BUCKET_NAME)
    except:
        cloud_price_df = make_dummy_cloud_price_df()

    cloud_price_df = cloud_price_df.loc[cloud_price_df['token_address'].str.upper() == token_address.upper()]

    if len(cloud_price_df) < 1:
        cloud_price_df = make_dummy_cloud_price_df()

    # If you want it as a string in 'YYYY-MM-DD' format instead of a date object
    cloud_price_df['date'] = pd.to_datetime(cloud_price_df['date']).dt.strftime('%Y-%m-%d')
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

    # # finds any unique dates from the cloud
    cloud_date_list = cloud_price_df['date'].unique()
    # # finds all the unique dates from our defillama df
    df_date_list = df['date'].unique()

    # unique_incentive_timestamps = [ts for ts in unique_incentive_timestamps if ts not in cloud_price_df['timestamp'].values]

    # # finds the unique dates from defillama that are not present in the cloud
    dates_to_check_list = [unique_date for unique_date in df_date_list if unique_date not in cloud_date_list]
    # # turns these unique dates into unix timestamps
    unique_timestamp_to_check = [date_to_unix_timestamp(str(unique_date)) for unique_date in dates_to_check_list]

    # # placeholder timestamp to use
    if len(unique_timestamp_to_check) < 1:
        unique_timestamp_to_check = [date_to_unix_timestamp(df_date_list[0])]


    data_list = []
    for unique_timestamp in unique_timestamp_to_check:

        start_timestamp = unique_timestamp
        end_timestamp = start_timestamp + 14400

        url = "https://coins.llama.fi/batchHistorical?coins=%7B%22" + blockchain + ":" + token_address + "%22:%20%5B" + str(end_timestamp) + ",%20" + str(start_timestamp) + "%5D%7D&searchWidth=600"
        # Send a GET request to the URL
        response = requests.get(url)

        # Check if the request was successful
        if response.status_code == 200:
            # Request was successful
            data = response.json()  # Parse the JSON response
            if len(data['coins']) > 0:
                data_list.append(data)
            else:
                unique_timestamp_to_check.append(1720569600)
                pass
        else:
            # Request failed
            print(f"Request failed with status code: {response.status_code}")
            print(response.text)  # Print the response content for more info on the error

        time.sleep(COOLDOWN_TIME)

    return data_list

# # makes a dataframe representation of our historic pricing info
def make_prices_df(data_list):
    
    df_list = []

    for data_json in data_list:
        if 'coins' in data_json and data_json['coins']:
            for token_address, coin_data in data_json['coins'].items():
                symbol = coin_data['symbol']
                prices = coin_data['prices']

                # Create DataFrame
                df = pd.DataFrame(prices)

                # Add symbol and token_address columns
                df['symbol'] = symbol
                df['token_address'] = token_address.split(':')[-1]  # Remove 'optimism:' prefix

                # Reorder columns
                df = df[['symbol', 'token_address', 'timestamp', 'price', 'confidence']]
                df['timestamp'] = df['timestamp'].astype(int)
                df['date'] = df['timestamp'].apply(unix_timestamp_to_date)
                # Calculate average price if there are multiple prices
                # if len(df) > 1:
                #     df = df.groupby(['symbol', 'token_address', 'timestamp'], as_index=False).agg({
                #         'price': 'mean',
                #         'confidence': 'mean'
                #     })

                df_list.append(df)

    # # will try combining our dataframe with our existing cloud one and dropping duplicates
    try:
        cloud_df = cs.read_zip_csv_from_cloud_storage(CLOUD_PRICE_FILENAME, CLOUD_BUCKET_NAME)
    except:
        cloud_df = make_dummy_cloud_price_df()

    if len(df_list) > 0:
        df = pd.concat(df_list, ignore_index=True)

        df = pd.concat([df, cloud_df])
        df = df.drop_duplicates(subset=['symbol', 'timestamp'])


    if len(df) > 0:
        df['timestamp'] = df['timestamp'].astype(int)
        df['date'] = df['timestamp'].apply(unix_timestamp_to_date)
        df = df[['symbol', 'token_address', 'timestamp', 'date','price']]
        cs.df_write_to_cloud_storage_as_zip(df, CLOUD_PRICE_FILENAME, CLOUD_BUCKET_NAME)
        return df
    else:
        return pd.DataFrame()  # Return an empty DataFrame if no valid data

# # takes in our incentives_per_day_df + incentives_timeseries_price_df
# # returns incentives_per_day_df with a new incentives_per_day_usd column that is the incentives_per day quantity * price
def find_daily_incentives_usd(incentives_per_day_df, incentives_timeseries_price_df):

    incentives_per_day_df['timestamp'] = incentives_per_day_df['timestamp'].astype(int)
    incentives_timeseries_price_df['timestamp'] = incentives_timeseries_price_df['timestamp'].astype(int)
    incentives_timeseries_price_df['price'] = incentives_timeseries_price_df['price'].astype(float)

    incentives_per_day_df = incentives_per_day_df.sort_values(by='timestamp')
    incentives_timeseries_price_df = incentives_timeseries_price_df.sort_values(by='timestamp')

    # Perform the merge_asof operation
    df_result = pd.merge_asof(incentives_per_day_df, incentives_timeseries_price_df[['timestamp', 'price']], 
                            on='timestamp', 
                            direction='nearest')
    
    # If you want to keep the original df_1 and just add the new 'price' column:
    incentives_per_day_df['price'] = df_result['price']


    incentives_per_day_df['incentives_per_day_usd'] = incentives_per_day_df['incentives_per_day'] * incentives_per_day_df['price']

    return incentives_per_day_df

# # runs all of our incentive data gathering functions and returns a dataframe of the info
def get_incentive_df():

    df = get_protocol_incentives_df()
    df = fill_incentive_days(df)
    df = get_incentives_unix_timestamps(df)
    data_list = get_token_price_json_list(df, PRICE_BLOCKCHAIN, OPTIMISM_TOKEN_ADDRESS)
    incentives_timeseries_price_df = make_prices_df(data_list)
    incentives_timeseries_price_df = incentives_timeseries_price_df.loc[incentives_timeseries_price_df['symbol'] == 'op']
    df = find_daily_incentives_usd(df, incentives_timeseries_price_df)

    return df

# # merges our two dataframes together
def combine_incentives_with_tvl(tvl_df, incentive_df):
    # Ensure 'date' columns are in the same format in both dataframes
    tvl_df['date'] = pd.to_datetime(tvl_df['date'])
    incentive_df['date'] = pd.to_datetime(incentive_df['date'])

    # Perform the left join
    result_df = pd.merge(
        tvl_df,
        incentive_df[[ # 'chain', 'platform', 'segment', 'partner', 'token', 'pool_type', 'protocol_slug', 'date', 
                      'protocol_slug', 'token', 'pool_type', 'date', 'epoch_token_incentives', 'incentives_per_day', 'price', 'incentives_per_day_usd']],
        how='left',
        left_on=['protocol', 'token', 'pool_type', 'date'],
        right_on=['protocol_slug', 'token', 'pool_type', 'date']
    )

    result_df = result_df.drop(['protocol_slug'], axis=1)

    result_df.fillna(0, inplace=True)

    return result_df

# # returns a dataframe of weth's price over time
def get_weth_price_over_time(df):

    data_list = get_token_price_json_list(df, PRICE_BLOCKCHAIN, WETH_TOKEN_ADDRESS)
    df = make_prices_df(data_list)

    return df

# # finds our start price, change in price usd, and change in price percentage per day relative to the start price
def get_weth_price_change_since_start(df):
    df[['timestamp']] = df[['timestamp']].astype(int)
    df['price'] = df['price'].astype(float)
    df = df.loc[df['symbol'] == 'WETH']
    temp_df = df.loc[df['timestamp'] == df['timestamp'].min()]
    start_price = temp_df['price'].min()
    df['weth_start_price'] = start_price

    df['weth_change_in_price_usd'] = df['price'] - df['weth_start_price']
    df['weth_change_in_price_percentage'] = (df['price'] / df['weth_start_price'] - 1)

    df = df.rename(columns = {'price': 'weth_price'})

    df = df.groupby('date').agg({
    'symbol': 'first',
    'token_address': 'first',
    'timestamp': 'first',
    'weth_price': 'mean',
    'weth_start_price': 'first',
    'weth_change_in_price_usd': 'mean',
    'weth_change_in_price_percentage': 'mean'
    }).reset_index()
    
    df = df.sort_values(by='timestamp')

    return df

# # converts a unix into a date
def unix_timestamp_to_date(unix_timestamp):
    # Convert Unix timestamp to datetime object
    date_object = dt.fromtimestamp(unix_timestamp)
    
    # Convert datetime object to string in desired format
    date_string = date_object.strftime("%Y-%m-%d")
    
    return date_string

# # merges those dataframes as the name implies
def merge_tvl_and_weth_dfs(tvl_df, weth_df):

    tvl_df = tvl_df.rename(columns={'price': 'op_price'})

    # Perform the left merge
    merged_df = tvl_df.merge(weth_df, on='date', how='left', suffixes=('', '_weth'))

    # Optionally, reorder the columns for better readability
    column_order = [
        'date', 'timestamp', 'chain', 'token', 'pool_type', 'protocol',
        'token_usd_amount', 'start_token_usd_amount', 'raw_change_in_usd', 'percentage_change_in_usd',
        'daily_tvl', 'epoch_token_incentives', 'incentives_per_day', 'op_price',
        'incentives_per_day_usd', 'symbol', 'token_address', 'timestamp_weth',
        'weth_price', 'weth_start_price', 'weth_change_in_price_usd', 'weth_change_in_price_percentage'
    ]
    merged_df = merged_df[column_order]

    # Reset the index if needed
    merged_df = merged_df.reset_index(drop=True)

    merged_df = merged_df.ffill()  # Forward fill: uses the last known value

    return merged_df


# # makes our top level aggreagate dafarame
def get_aggregate_top_level_df(df):
    
    df[['token_usd_amount', 'start_token_usd_amount', 'raw_change_in_usd', 'daily_tvl', 'epoch_token_incentives', 'incentives_per_day', 'op_price', 'incentives_per_day_usd', 'weth_price', 'weth_start_price', 'weth_change_in_price_usd', 'weth_change_in_price_percentage']] = df[['token_usd_amount', 'start_token_usd_amount', 'raw_change_in_usd', 'daily_tvl', 'epoch_token_incentives', 'incentives_per_day', 'op_price', 'incentives_per_day_usd', 'weth_price', 'weth_start_price', 'weth_change_in_price_usd', 'weth_change_in_price_percentage']].astype(float)
    df['date'] = pd.to_datetime(df['date'])

    # Group by day and aggregate the specified columns
    aggregated_df = df.groupby(df['date']).agg({
        'token_usd_amount': 'sum',
        'start_token_usd_amount': 'sum',
        'raw_change_in_usd': 'sum',
        'daily_tvl': 'sum',
        'epoch_token_incentives': 'sum',
        'incentives_per_day': 'sum',
        'op_price': 'max',
        'incentives_per_day_usd': 'sum',
        'symbol': 'first',
        'weth_price': 'min',
        'weth_start_price': 'min',
        'weth_change_in_price_usd': 'min',
        'weth_change_in_price_percentage': 'min'
    }).reset_index()
    
    # # tried changing this one
    min_start_tvl = aggregated_df['token_usd_amount'].tolist()[0]

    aggregated_df['start_token_usd_amount'] = min_start_tvl
    aggregated_df['raw_change_in_usd'] = aggregated_df['token_usd_amount'] - aggregated_df['start_token_usd_amount']

    aggregated_df['percentage_change_in_usd'] = (aggregated_df['token_usd_amount'] / aggregated_df['start_token_usd_amount'] - 1)

    aggregated_df['cumulative_incentives_usd'] = aggregated_df['incentives_per_day_usd'].cumsum()

    aggregated_df['tvl_to_incentive_roi_percentage'] = aggregated_df['raw_change_in_usd'] / aggregated_df['cumulative_incentives_usd']

    return aggregated_df

# # will remove protocols that are missing a lot of data
def clean_up_bad_data_protocols(df):

    df = df.loc[df['incentives_per_day'] < df['token_usd_amount']]

    return df

# # does same calculation as our aggregate for each pool
def calculate_individual_protocol_incentive_roi(df):

    # df_list = []

    # unique_protocol_list = df['protocol'].unique()

    # for unique_protocol in unique_protocol_list:
    #     temp_df = df.loc[df['protocol'] == unique_protocol]
    #     unique_protocol_token_list = temp_df['token'].unique()

    #     for unique_token in unique_protocol_token_list:
    #         temp_df = temp_df.loc[temp_df['token'] == unique_token]

    #         unique_pool_type_list = temp_df['pool_type'].unique()

    #         for unique_pool in unique_pool_type_list:
    #             temp_df = temp_df.loc[temp_df['pool_type'] == unique_pool]

    #             unique_chain_list = temp_df['chain'].unique()

    #             for unique_chain in unique_chain_list:
    #                 temp_df = temp_df.loc[temp_df['chain'] == unique_chain]

    #                 temp_df = temp_df.sort_values(['date'], ascending=True)

    #                 temp_df['cumulative_incentives_usd'] = temp_df['incentives_per_day_usd'].cumsum()

    #                 print(temp_df)
    #                 df_list.append(temp_df)
    
    # df = pd.concat(df_list)

    df = df.sort_values(['protocol', 'token', 'pool_type', 'chain', 'date'])  # Assuming you have a 'date' column
    df['cumulative_incentives_usd'] = df.groupby(['protocol', 'token', 'pool_type', 'chain'])['incentives_per_day_usd'].cumsum()

    df['tvl_to_incentive_roi_percentage'] = df['raw_change_in_usd'] / df['cumulative_incentives_usd']

    return df

# # will make a dataframe that is WETH price adjusted
def get_weth_adjusted_df(df):
    df[['token_usd_amount', 'start_token_usd_amount', 'raw_change_in_usd', 'percentage_change_in_usd', 'daily_tvl', 'op_price', 'incentives_per_day_usd', 'weth_price', 'weth_start_price', 'weth_change_in_price_usd', 'weth_change_in_price_percentage', 'cumulative_incentives_usd', 'tvl_to_incentive_roi_percentage']] = df[['token_usd_amount', 'start_token_usd_amount', 'raw_change_in_usd', 'percentage_change_in_usd', 'daily_tvl', 'op_price', 'incentives_per_day_usd', 'weth_price', 'weth_start_price', 'weth_change_in_price_usd', 'weth_change_in_price_percentage', 'cumulative_incentives_usd', 'tvl_to_incentive_roi_percentage']].astype(float)
    
    # # if ETH went up in price then we make the adjustment negative
    # # if ETH went down in price then we make the adjustment positive
    df['temp_weth_price_adjusted_multiplier'] = df['weth_change_in_price_percentage'] * -1

    # # we add 1 to allow for easy multiplication
    df['temp_weth_price_adjusted_multiplier'] = df['temp_weth_price_adjusted_multiplier'] + 1

    # token_usd_amount: number;
    # raw_change_in_usd: number;
    # incentives_per_day_usd: number;
    # weth_change_in_price_percentage: number;
    # percentage_change_in_usd: number;
    # tvl_to_incentive_roi_percentage: number;

    adjustment_column_list = ['token_usd_amount', 'raw_change_in_usd', 'incentives_per_day_usd', 'weth_change_in_price_percentage', 'percentage_change_in_usd', 'tvl_to_incentive_roi_percentage']

    # # we essentially multiply each respective column by its weth_adjustment multiplier and make it a new column
    for adjustment_column in adjustment_column_list:
        new_column_name = 'adjusted_' + adjustment_column
        
        df[new_column_name] = df[adjustment_column] * df['temp_weth_price_adjusted_multiplier']

    return df

# @app.route('/api/update_data', methods=['GET'])
# @limiter.limit("100 per hour")  # Adjust this limit as needed
def run_all():
    protocol_df = get_protocol_pool_config_df()

    # # Here **
    # protocol_df = protocol_df.loc[protocol_df['protocol_slug'] == 'fluid']

    protocol_slug_list = protocol_df['protocol_slug'].tolist()
    protocol_blockchain_list = protocol_df['chain'].tolist()
    pool_type_list = protocol_df['pool_type'].tolist()
    token_list = protocol_df['token'].tolist()
    chain_list = protocol_df['chain'].tolist()

    df_list = []

    start_unix = int(date_to_unix_timestamp(START_DATE))

    last_slug = ''
    last_token = ''
    last_pool_type = ''
    i = 0

    while i < len(protocol_slug_list):

        protocol_slug = protocol_slug_list[i]
        protocol_blockchain = protocol_blockchain_list[i]
        pool_type = pool_type_list[i]
        token = token_list[i]
        chain = chain_list[i]
        
        # # we will only send another api ping if we are using a new slug
        if last_slug != protocol_slug:
            if pool_type == 'AMM':
                old_protocol_slug = protocol_slug
                protocol_slug = get_dex_pool_pool_id(protocol_slug)
                data = get_historic_dex_tvl_json(protocol_slug)
                protocol_slug = old_protocol_slug
            else:
                data = get_historic_protocol_tvl_json(protocol_slug)
            time.sleep(COOLDOWN_TIME)
        
        elif pool_type != last_pool_type:
            if pool_type == 'AMM':
                old_protocol_slug = protocol_slug
                protocol_slug = get_dex_pool_pool_id(protocol_slug)
                data = get_historic_dex_tvl_json(protocol_slug)
                protocol_slug = old_protocol_slug
            else:
                data = get_historic_protocol_tvl_json(protocol_slug)
            time.sleep(COOLDOWN_TIME)
        # print(data)
        # Write the API response to a JSON file
        # with open('contango_api_response.json', 'w') as file:
        #     json.dump(data, file, indent=4)

        else:
            pass
        

        # if last_pool_type != pool_type:
        df = get_pool_type_df(data, protocol_blockchain, pool_type)
        
        df = filter_start_timestamp(df, start_unix)
        df['pool_type'] = pool_type
        if pool_type != 'AMM':
            df = transpose_df(df)
        elif pool_type == 'AMM':
            df['token'] = token
            df = df.rename(columns={'tvlUsd': 'token_amount'})
            df = df[['timestamp', 'token', 'token_amount', 'pool_type']]

        df = add_start_token_amount_column(df)
        df = add_change_in_token_amounts(df)

        df.rename(columns = {'token_amount':'token_usd_amount', 'start_token_amount': 'start_token_usd_amount'}, inplace = True)

        df = find_tvl_over_time(df)
        df.to_csv('test_test.csv', index=False)

        df['protocol'] = protocol_slug
        df['chain'] = chain

        # # trying to cleanup token dataframes closer to the source
        df = df_token_cleanup(protocol_df, df)
        
        # # tries to thin out data where each day only has one datapoint for this combo
        df = df.drop_duplicates(subset=['date', 'chain', 'token', 'pool_type', 'protocol'], keep='last')

        df_list.append(df)
        
        # else:
        #     pass

        # # updates our last known values to reduce api calls and computation needs
        last_slug = protocol_slug
        last_pool_type = pool_type

        i += 1

    df = pd.concat(df_list)

    # # tries to thin out data where each day only has one datapoint for this combo
    df = df.drop_duplicates(subset=['date', 'chain', 'token', 'pool_type', 'protocol'], keep='last')

    # df = df_token_cleanup(protocol_df, df)
    incentive_df = get_incentive_df()
    df = combine_incentives_with_tvl(df, incentive_df)

    tvl_df = df
    df = get_weth_price_over_time(df)

    df = get_weth_price_change_since_start(df)

    merged_df = merge_tvl_and_weth_dfs(tvl_df, df)

    merged_df = merged_df.drop_duplicates(subset=['date', 'chain', 'token', 'pool_type', 'protocol'])

    merged_df = clean_up_bad_data_protocols(merged_df)

    # merged_df = fix_protocol_segments(merged_df)

    aggregate_df = get_aggregate_top_level_df(merged_df)

    merged_df = calculate_individual_protocol_incentive_roi(merged_df)

    aggregate_df = aggregate_df.fillna(0)
    
    merged_df = merged_df.fillna(0)

    aggregate_df = aggregate_df.replace([np.inf, -np.inf], 0)
    merged_df = merged_df.replace([np.inf, -np.inf], 0)

    # # adds columns for our weth_price_adjustment
    aggregate_df = get_weth_adjusted_df(aggregate_df)
    merged_df = get_weth_adjusted_df(merged_df)

    # # to help weed out the any days that haven't been indexed yet
    aggregate_df = aggregate_df.loc[aggregate_df['raw_change_in_usd'] >= 0]
    # aggregate_df = aggregate_df.loc[aggregate_df['date'] <= '2024-10-07']
    # merged_df = merged_df.loc[merged_df['timestamp'] <= 1728345600]

    cs.df_write_to_cloud_storage_as_zip(merged_df, CLOUD_DATA_FILENAME, CLOUD_BUCKET_NAME)

    cs.df_write_to_cloud_storage_as_zip(aggregate_df, CLOUD_AGGREGATE_FILENAME, CLOUD_BUCKET_NAME)
    
    return jsonify({"status": 200}), 200


@lru_cache(maxsize=1)
def get_incentive_combo_list() -> List[str]:
    incentive_history_df = pd.read_csv('protocol_incentive_history.csv')
    incentive_history_df['combo_name'] = (
        incentive_history_df['chain'] +
        incentive_history_df['protocol_slug'] +
        incentive_history_df['token'] +
        incentive_history_df['pool_type']
    )
    return incentive_history_df['combo_name'].unique().tolist()

@lru_cache(maxsize=100)
def cached_read_zip_csv_from_cloud_storage(filename, bucket_name):
    print(f"Reading {filename} from {bucket_name}")  # To show when it's actually reading
    return cs.read_zip_csv_from_cloud_storage(filename, bucket_name)


# does as the name implies
# @app.route('/api/pool_tvl_incentives_and_change_in_weth_price', methods=['GET'])
# @limiter.limit("100 per hour")  # Adjust this limit as needed
def get_pool_tvl_incentives_and_change_in_weth_price():
    # df = cs.read_zip_csv_from_cloud_storage(CLOUD_DATA_FILENAME, CLOUD_BUCKET_NAME)
    df = cached_read_zip_csv_from_cloud_storage(CLOUD_DATA_FILENAME, CLOUD_BUCKET_NAME)
    df['combo_name'] = df['chain'] + df['protocol'] + df['token'] + df['pool_type']
    
    incentive_combo_list = get_incentive_combo_list()
    df = df[df['combo_name'].isin(incentive_combo_list)]
    
    columns_to_keep = ['date', 'chain', 'protocol', 'token', 'pool_type', 'token_usd_amount', 'raw_change_in_usd', 'percentage_change_in_usd', 'incentives_per_day_usd', 'weth_change_in_price_percentage', 'tvl_to_incentive_roi_percentage',
    'adjusted_token_usd_amount', 'adjusted_raw_change_in_usd', 'adjusted_incentives_per_day_usd', 'adjusted_percentage_change_in_usd', 'adjusted_tvl_to_incentive_roi_percentage']
    df = df[columns_to_keep]
    
    # Convert 'date' column to datetime, sort, and format to ISO 8601
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    df['date'] = df['date'].dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    
    result: Dict[str, List[Dict]] = {}
    for name, group in df.groupby(['protocol', 'token', 'pool_type', 'chain']):
        key = f"{name[0].capitalize()} {name[3].capitalize()}: {name[1].upper()} {name[2].capitalize()}"  # Create a string key
        result[key] = group.drop(['protocol', 'token', 'pool_type', 'chain'], axis=1).to_dict('records')
    
    return jsonify(result)

# # returns our cloud aggregate data
# @app.route('/api/aggregate_data', methods=['GET'])
# @limiter.limit("100 per hour")  # Adjust this limit as needed
def get_aggregate_summary_data():

    df = cached_read_zip_csv_from_cloud_storage(CLOUD_AGGREGATE_FILENAME, CLOUD_BUCKET_NAME)

    data = df.to_dict(orient='records')

    return jsonify(data)


# # does as the name implies
def get_dex_pool_config():
    df = pd.read_csv('dex_pool_config.csv')

    return df

def fix_protocol_segments(df):

    protocol_fix_list = ['extra-finance', 'morpho-blue', 'toros']

    protocol_pool_df = get_protocol_pool_config_df()

    for protocol in protocol_fix_list:
        temp_pool_df = protocol_pool_df.loc[protocol_pool_df['protocol_slug'] == protocol]
        pool_type = temp_pool_df['segment'].unique()[0]

        df.loc[df['protocol'] == protocol, 'pool_type'] = pool_type

    return df

# # takes a slug and gives back a pool_id
def get_dex_pool_pool_id(protocol_slug):

    dex_config_df = get_dex_pool_config()

    dex_config_df = dex_config_df.loc[dex_config_df['protocol_slug'] == protocol_slug]

    pool_id = dex_config_df['pool_id'].unique()[0]

    return pool_id

# if __name__ == '__main__':
#     app.run(use_reloader=True, port=8000, threaded=True, DEBUG=True)

start_time = time.time()
# run_all()
try:
    run_all()
except:
    pass
end_time = time.time()
print('Finished in: ', end_time - start_time)

# df = cs.read_zip_csv_from_cloud_storage(CLOUD_DATA_FILENAME, CLOUD_BUCKET_NAME)
# df = get_aggregate_top_level_df(df)
# df = df.loc[df['protocol'] == 'aave-v3']
# print(df)
# df.to_csv('super_fest.csv', index=False)

##