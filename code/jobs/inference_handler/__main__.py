#%%
## Import librairies
import os
import argparse
import logging
import json
import requests

import numpy as np
import pandas as pd
import torch

from datasets import Dataset
from transformers import AutoTokenizer #,AutoModelForSequenceClassification


#%%
## Define logging behavior
logging.getLogger("tokenizers").setLevel(logging.CRITICAL)  
logging.getLogger("transformers").setLevel(logging.CRITICAL) 
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


#%%
## Manage job parameters
parser = argparse.ArgumentParser()
## Required for model handler demo
parser.add_argument("--server_url", help="URL of the mlflow server", required=False, default=os.environ['MLFLASK_URL']+"/predict")
parser.add_argument("--model_name", help="Name of the model to call", required=False, default='CommentCLF1')
parser.add_argument("--input_texts", help="The texts for inference test, e.g. ['sentence1', 'sentence2', 'sentence3', 'sentence4']"
                    , default = "['Very good movie!', 'Not really enjoyable, not interesting at all, to be honest it has nothing', 'I was looking forward to this movie. Trustworthy actors', 'What a nasty cynical film. Apparently this sad excuse for a dramatic urban look at what 20 year olds do whilst crawling through the gutter of Sydney nightlife is supposed to be somehow connecting with its target market.']"
                    , required = True)
## Permanent params of handler
parser.add_argument("--test_batchsize", help="Batch size for the test and val datasets", type=int, default = 4, required = False)
parser.add_argument("--tokenizer_name", help="name of the pretrained model to load from huggingface repository", default = 'prajjwal1/bert-tiny', required = False)
parser.add_argument("--device", help="Device where is computed Deep learning, 'cpu' or 'cuda'", default = 'cpu', required = False)

inference_params = vars(parser.parse_args()) # args to dict

model_name = inference_params['model_name']
input_texts = inference_params['input_texts']
exec('input_texts='+input_texts)
print('Input Texts: '+str(input_texts))

## Class dict
classdict = {0: 'Negative', 1: 'Positive'}


#%% Load Tokenizer from Hunggingface 
### Define the device to use by torch
device = torch.device(inference_params['device'])
### Prepare tokenizer
tokenizer = AutoTokenizer.from_pretrained(inference_params['tokenizer_name'])
def tokenization(example, tokenizer=tokenizer):
    return tokenizer(example["text"], truncation = True, padding = True, max_length = 500)


#%% Inference Data Preprocessing
### Load train and test datasets, and make val dataset
test_df = pd.DataFrame(input_texts, columns=['text'])
### Convert to Dataset type
test_ds = Dataset.from_pandas(test_df)
### Apply tokenizer on datasets
test_ds = test_ds.map(tokenization, batched=True)
### Create DataLoaders
test_ds.set_format(type='torch', columns=['input_ids', 'attention_mask'])
test_loader = torch.utils.data.DataLoader(test_ds, batch_size=inference_params['test_batchsize'], shuffle = False)


#%% Inference Handling
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)


def post(data, model:str, serve_url=inference_params['server_url'], data_type='json'):
    """Inference with POST requests """
    if data_type == 'json':
        headers = {'Content-Type': 'application/json'}
    model_input = json.dumps({"data":data, "model":model}, cls=NumpyEncoder)
    response = requests.post(serve_url, headers=headers, data=model_input, verify=False)
    response = response._content.decode('utf-8')
    try:
        response = json.loads(response)
        return response
    except:
        return response


def predict(test_loader, model):
    with torch.no_grad():
        all_preds = []
        for batch in test_loader:            
            data = [batch['input_ids'].numpy(), batch['attention_mask'].numpy()]
            preds = post(data, model)['response'] # like "[1 0 1 0]"
            preds = np.array(preds[1:-1].split()).astype(int) # like array([1., 0., 1., 0.])
            # print(preds) ## Debug use
            # print(type(preds)) ## Debug use
            all_preds.append(preds)
        all_preds = np.vstack(all_preds)
        # all_preds = np.argmax(all_preds, axis=1)
    return np.vectorize(classdict.get)(all_preds)

print('prediction: '+str(predict(test_loader, model_name)))