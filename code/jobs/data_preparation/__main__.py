import os
import argparse
import s3fs
import pandas as pd
from datasets import load_dataset


#%%
## Arguments
parser = argparse.ArgumentParser()
parser.add_argument("--dataset", help="s3bucket", required=False, default='imdb')
parser.add_argument("--s3key", help="s3key", required=False, default=os.environ['AWS_ACCESS_KEY_ID'])
parser.add_argument("--s3secret", help="s3secret", required=False, default=os.environ['AWS_SECRET_ACCESS_KEY'])
parser.add_argument("--s3bucket", help="s3bucket", required=False, default=os.environ['AWS_BUCKET'])
parser.add_argument("--s3bucket_train_csv", help="S3 path where saved csv for training", default = '/cleaned-data/train/', required = False)
parser.add_argument("--s3bucket_test_csv", help="S3 path where saved csv for testing", default = '/cleaned-data/test/', required = False)
# parser.add_argument("--mlflask_url", help="URL of the mlflow server", default=os.environ['MLFLASK_URL'],)
# parser.add_argument("--mlflowserver_url", help="URL of the mlflow server", default=os.environ['MLFLOWSERVER_URL'],)

args = parser.parse_args()
s3key = args.s3key
s3secret = args.s3secret
s3bucket = args.s3bucket
dataset_name = args.dataset


#%%
## Data loading and exporting to s3fs
## Connection using s3fs
fs = s3fs.S3FileSystem(key=s3key, secret=s3secret)
bucket_name = s3bucket

## If preprocessed data already exists, skip the preprocessing
try:
    s3bucket_train_csv = args.s3bucket_train_csv
    s3bucket_test_csv = args.s3bucket_test_csv
    train_csv = fs.ls(bucket_name + s3bucket_train_csv)[-1]
    test_csv = fs.ls(bucket_name + s3bucket_test_csv)[-1]
    with fs.open('s3://' + train_csv) as f:
        train_init_df = pd.read_csv(f, sep='^([^,]+),', engine='python', usecols=['label', 'text'])
    with fs.open('s3://' + test_csv) as f:    
        test_df = pd.read_csv(f, sep='^([^,]+),', engine='python', usecols=['label', 'text'])
    print('Preprocessed data already exists, Skipping step1.data_preparation & step2.preprocessing')
    
except:
    ## Load IMDB datasets from Huggingface datasets
    train_dataset = load_dataset(dataset_name, split = "train")
    test_dataset = load_dataset(dataset_name, split = "test")
    ## Transform to pandas
    train_df = pd.DataFrame({"text":train_dataset["text"], "label":train_dataset["label"]})
    test_df = pd.DataFrame({"text":test_dataset["text"], "label":train_dataset["label"]})
    print('Data converted to dataframes')
    
    ## Export in CSV to the datalake (S3)
    with fs.open('s3://' + bucket_name + "/train.csv", 'w') as f:
        train_df.to_csv(f, index=False, sep="\t")
    with fs.open('s3://' + bucket_name + "/test.csv", 'w') as f:
        test_df.to_csv(f, index=False, sep="\t")
    print('Data exported to S3')
    
    ## Verify files in the bucket
    files = fs.ls(bucket_name)
    print('Connected to S3 bucket:', bucket_name)
    print('Listing files:', files)
    
    ## Show examples of csvs saved in the bucket
    with fs.open('s3://' + bucket_name + "/train.csv") as f:
        train_df = pd.read_csv(f, sep="\t")
    print("Example of Train df")
    print(train_df.head())
    print("length:", len(train_df))
    with fs.open('s3://' + bucket_name + "/test.csv") as f:
        test_df = pd.read_csv(f, sep="\t")
    print("Example of Test df")
    print(test_df.head())
    print("length:", len(test_df))
