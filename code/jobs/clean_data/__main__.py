# Import libraries
import os
import argparse
import logging
import s3fs
import pandas as pd

## Define logging behavior
logging.getLogger("tokenizers").setLevel(logging.CRITICAL)
logging.getLogger("transformers").setLevel(logging.CRITICAL)
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Manage job parameters
parser = argparse.ArgumentParser()
parser.add_argument("--s3bucket_train_csv", help="S3 path where saved csv for training", default='/cleaned-data/train/',
                    required=False)
parser.add_argument("--s3bucket_test_csv", help="S3 path where saved csv for testing", default='/cleaned-data/test/',
                    required=False)
parser.add_argument("--s3key", help="s3key", required=False, default=os.environ['AWS_ACCESS_KEY_ID'])
parser.add_argument("--s3secret", help="s3secret", required=False, default=os.environ['AWS_SECRET_ACCESS_KEY'])
parser.add_argument("--s3bucket", help="s3bucket", required=False, default=os.environ['AWS_BUCKET'])

preprocess_params = vars(parser.parse_args())  # args to dict

# Arguments
s3key = preprocess_params['s3key']
s3secret = preprocess_params['s3secret']
s3bucket = preprocess_params['s3bucket']
s3bucket_train_csv = preprocess_params['s3bucket_train_csv']
s3bucket_test_csv = preprocess_params['s3bucket_test_csv']

# Connection using s3fs
fs = s3fs.S3FileSystem(key=s3key, secret=s3secret)
bucket_name = s3bucket

# If preprocessed data already exists, skip the preprocessing
try:
    train_csv = fs.ls(bucket_name + s3bucket_train_csv)[-1]
    test_csv = fs.ls(bucket_name + s3bucket_test_csv)[-1]
    with fs.open('s3://' + train_csv) as f:
        train_init_df = pd.read_csv(f, sep='^([^,]+),', engine='python', usecols=['label', 'text'])
    with fs.open('s3://' + test_csv) as f:
        test_df = pd.read_csv(f, sep='^([^,]+),', engine='python', usecols=['label', 'text'])
    print('Preprocessed data already exists, Skipping step1.data_preparation & step2.preprocessing')

except:
    # Read & Write
    def read_data():
        with fs.open('s3://' + bucket_name + "/train.csv") as f:
            train_df = pd.read_csv(f, sep='\t', engine='python')
        with fs.open('s3://' + bucket_name + "/test.csv") as f:
            test_df = pd.read_csv(f, sep='\t', engine='python')
        return train_df, test_df


    def write_data(train_df, test_df):
        path_train = 's3://' + bucket_name + s3bucket_train_csv + "train.csv"
        path_test = 's3://' + bucket_name + s3bucket_test_csv + "test.csv"
        print(path_train)
        with fs.open(path_train, 'w') as f:
            train_df.to_csv(f, sep=',', index=False)
        print(path_test)
        with fs.open(path_test, 'w') as f:
            test_df.to_csv(f, sep=',', index=False)


    ## Cleansing
    train_df, test_df = read_data()
    train_df['text'] = train_df['text'].str.replace('[^\w\s]', '')
    test_df['text'] = test_df['text'].str.replace('[^\w\s]', '')
    train_df = train_df[['label', 'text']]
    test_df = test_df[['label', 'text']]
    write_data(train_df, test_df)

    print(train_df.head())
    print(test_df.head())
