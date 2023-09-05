#%%
## Import librairies
import os
import argparse
import copy
import logging
import time
import s3fs

import mlflow
import numpy as np
import pandas as pd
import torch
from datasets import Dataset
from fastprogress import master_bar, progress_bar
from mlflow.tracking import MlflowClient
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from transformers import (AdamW, AutoModelForSequenceClassification, AutoTokenizer)


#%%
## Define logging behavior
logging.getLogger("tokenizers").setLevel(logging.CRITICAL)  
logging.getLogger("transformers").setLevel(logging.CRITICAL) 
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


#%%
## Manage job parameters
parser = argparse.ArgumentParser()
parser.add_argument("--nb_train_epochs", help="number of epochs for training the model", type=int, default = 10, required = False)
parser.add_argument("--model_name", help="name of the pretrained model to load from huggingface repository", default = 'prajjwal1/bert-tiny', required = False)
parser.add_argument("--train_batchsize", help="Batch size for the train dataset", type=int, default = 16, required = False)
parser.add_argument("--test_batchsize", help="Batch size for the test and val datasets", type=int, default = 16, required = False)
parser.add_argument("--nb_unfrozen_layers", help="Number of layers to unfreeze from the last layer. If -1 (default), no layer will be frozen", type=int, default = -1, required = False)
parser.add_argument("--train_subset_size", help="Subset size of the train dataset", type=int, default = 5000, required = False)
parser.add_argument("--test_subset_size", help="Subset size of the test dataset", type=int, default = 1000, required = False)
parser.add_argument("--seed", help="Seed to reproduce the same subsetting", type=int, default = 60, required = False)
parser.add_argument("--device", help="Device where is computed Deep learning, 'cpu' or 'cuda'", default = 'cpu', required = False)
parser.add_argument("--mlflowserver_url", help="URL of the mlflow server", required = True)
parser.add_argument("--s3bucket_train_csv", help="S3 path where saved csv for training", default = '/cleaned-data/train/', required = True)
parser.add_argument("--s3bucket_test_csv", help="S3 path where saved csv for testing", default = '/cleaned-data/test/', required = True)
parser.add_argument("--mlflow_experiment_name", help="Name of the experiment into mlflow", default=os.environ['MLFLOW_EXP_NAME'], required = False)
parser.add_argument("--s3key", help="s3key", required=False, default=os.environ['AWS_ACCESS_KEY_ID'])
parser.add_argument("--s3secret", help="s3secret", required=False, default=os.environ['AWS_SECRET_ACCESS_KEY'])
parser.add_argument("--s3bucket", help="s3bucket", required=False, default=os.environ['AWS_BUCKET'])

training_params = vars(parser.parse_args()) # args to dict


#%%
## Load Dataset, tokenize and dataloader
### Load train and test datasets, and make val dataset
s3key = training_params['s3key']
s3secret = training_params['s3secret']
s3bucket = training_params['s3bucket']
s3bucket_train_csv = training_params['s3bucket_train_csv']
s3bucket_test_csv = training_params['s3bucket_test_csv']

## Connection using s3fs
fs = s3fs.S3FileSystem(key=s3key, secret=s3secret)
bucket_name = s3bucket

train_csv = fs.ls(bucket_name + s3bucket_train_csv)[-1]
test_csv = fs.ls(bucket_name + s3bucket_test_csv)[-1]

print(train_csv)
print(test_csv)

with fs.open('s3://' + train_csv) as f:
    train_init_df = pd.read_csv(f, sep='^([^,]+),', engine='python')
    train_init_df = train_init_df[['label', 'text']]
with fs.open('s3://' + test_csv) as f:    
    test_df = pd.read_csv(f, sep='^([^,]+),', engine='python')
    test_df = test_df[['label', 'text']]

print(train_init_df.head())
print(test_df.head())

train_init_df = train_init_df.sample(frac = 1.0, random_state = training_params['seed'])[:training_params['train_subset_size']]
train_df, val_df = train_test_split(train_init_df, test_size=0.2, random_state = training_params['seed']) # split into train/val datasets
test_df = test_df.sample(frac = 1.0, random_state = training_params['seed'])[:training_params['test_subset_size']]

    
#%%
### Convert to Dataset type
train_ds = Dataset.from_pandas(train_df)
val_ds = Dataset.from_pandas(val_df)
test_ds = Dataset.from_pandas(test_df)

### Prepare tokenizer
tokenizer = AutoTokenizer.from_pretrained(training_params['model_name'])
def tokenization(example, tokenizer=tokenizer):
    return tokenizer(example["text"], truncation = True, padding = True, max_length = 500)

### Apply tokenizer on datasets
train_ds = train_ds.map(tokenization, batched=True)
test_ds = test_ds.map(tokenization, batched=True)
val_ds = val_ds.map(tokenization, batched=True)

### Create DataLoaders
train_ds.set_format(type='torch', columns=['input_ids', 'attention_mask', 'label'])
val_ds.set_format(type='torch', columns=['input_ids', 'attention_mask', 'label'])
test_ds.set_format(type='torch', columns=['input_ids', 'attention_mask', 'label'])

train_dataloader = torch.utils.data.DataLoader(train_ds, batch_size=training_params['train_batchsize'], shuffle = True)
val_dataloader = torch.utils.data.DataLoader(val_ds, batch_size=training_params['test_batchsize'], shuffle = False)
test_dataloader = torch.utils.data.DataLoader(test_ds, batch_size=training_params['test_batchsize'], shuffle = False)


#%%
## Define the device to use by torch
device = torch.device(training_params['device'])
## Load Model from Hunggingface in order to finetune it on a classification task
model = AutoModelForSequenceClassification.from_pretrained(training_params['model_name']).to(device)


#%%
### Function to freeze every layer except the last ones
def freeze_all_layers_except_last_ones(model, nb_unfrozenlayers = -1):
	if nb_unfrozenlayers != -1:
		for param in list(model.parameters()):
		    param.requires_grad = True
		for param in list(model.parameters())[:-nb_unfrozenlayers]:
		    param.requires_grad = False

### Freeze N last layers
freeze_all_layers_except_last_ones(model, training_params['nb_unfrozen_layers'])

### Show number of parameters to learn
nb_parameters = sum(p.numel() for p in model.parameters() if p.requires_grad==True)
print(f'Number of paramaters to learn after freezing: {nb_parameters}')


#%%
## Train and test functions
class AverageMeter(object):
    """Computes and stores the average and current value"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


def train(train_loader, model, optimizer, mb):
    model.train()
    
    loss_meter = AverageMeter()
    batch_time = AverageMeter()
    all_preds = []
    all_targets = []
    
    end = time.time()
    for batch in progress_bar(train_loader, parent=mb):
        input_ids = batch['input_ids'].to(device)
        attention_mask = batch['attention_mask'].to(device)
        labels = batch['label']
        all_targets.append(torch.reshape(labels, (labels.shape[0],1)).numpy())
        # all gradients to zero
        optimizer.zero_grad()
        # forward pass to compute the loss
        outputs = model(input_ids, attention_mask=attention_mask, labels=labels.to(device))
        loss, preds = outputs["loss"], outputs["logits"]
        loss_meter.update(loss.item(), input_ids.shape[0])
        # backward pass to compute gradients
        loss.backward()
        # update weights according to gradients
        optimizer.step()
        batch_time.update(time.time() - end)
        end = time.time()
        mb.child.comment = f'Loss: {loss_meter.avg:0.4f} - Batch time: {batch_time.avg:0.3f}'
        all_preds.append(preds.cpu().detach().numpy())
        
    # Keep all predictions and targets to compute metrics after training
    all_preds = np.vstack(all_preds)
    all_preds = np.argmax(all_preds, axis=1)
    all_targets = np.vstack(all_targets)
    
    return loss_meter.avg, all_preds, all_targets


def test(test_loader, model, mb):
    with torch.no_grad():
        model.eval()

        loss_meter = AverageMeter()
        all_preds = []
        all_targets = []

        for batch in progress_bar(test_loader, display=False if mb==None else True, parent=mb):
            input_ids = batch['input_ids'].to(device)
            attention_mask = batch['attention_mask'].to(device)
            labels = batch['label']
            all_targets.append(torch.reshape(labels, (labels.shape[0],1)).numpy())
            
            if len(labels) != 0:
                labels = labels.to(device)
                outputs = model(input_ids, attention_mask=attention_mask, labels=labels)
                loss, preds = outputs["loss"], outputs["logits"]
                loss_meter.update(loss.item(), preds.shape[0])
            else:
                preds, _ = model(input_ids, attention_mask)
            all_preds.append(preds.cpu().numpy())

        all_preds = np.vstack(all_preds)
        all_preds = np.argmax(all_preds, axis=1)
        all_targets = np.vstack(all_targets)
    
    return loss_meter.avg, all_preds, all_targets


#%%
## Learning Part
optimizer = AdamW(model.parameters(), lr=1e-4)

### Connection to MLFlow
mlflow.set_tracking_uri(training_params['mlflowserver_url'])
mlflow.set_registry_uri(training_params['mlflowserver_url'])
client = MlflowClient()
EXPERIMENT_NAME = training_params['mlflow_experiment_name']
mlflow.set_experiment(EXPERIMENT_NAME)
exp = client.get_experiment_by_name(EXPERIMENT_NAME)

with mlflow.start_run() as run:
    # Log hyperparameters into mlflow
    mlflow.log_params(training_params),
    mlflow.log_param('optimizer', type(optimizer).__name__) 
    mlflow.log_params(optimizer.defaults)

    best_epoch = -1
    best_f_scores = 0.0
    best_val_loss = 100
    mb = master_bar(range(training_params['nb_train_epochs']))
    since = time.time()
    # Learning loop
    for epoch in mb:
        start_time = time.time()

        avg_loss, train_preds, train_targets = train(train_dataloader, model, optimizer, mb)
        avg_val_loss, val_preds, val_targets = test(val_dataloader, model, mb)
        # Compute metrics according predictions and targets
        _, _, f_scores_train, _ = precision_recall_fscore_support(train_targets, train_preds, average = "weighted")
        _, _, f_scores_val, _ = precision_recall_fscore_support(val_targets, val_preds, average = "weighted")

        elapsed = time.time() - start_time
        # Keep best_model, best val metric and loss in memory
        if best_f_scores < f_scores_val:
            best_f_scores = f_scores_val
            best_val_loss = avg_val_loss
            best_epoch = epoch + 1
            best_model = copy.deepcopy(model)
        # Log training steps
        # logger.info(f'Epoch {epoch+1} - Train_loss: {avg_loss:.4f} - Train_f1: {f_scores_train:.4f} Val_loss: {avg_val_loss:.4f}  Val_f1: {f_scores_val:.4f} time: {elapsed:.0f}s')
        mb.write(f'Epoch {epoch+1} - Train_loss: {avg_loss:.4f} - Train_f1: {f_scores_train:.4f} Val_loss: {avg_val_loss:.4f}  Val_f1: {f_scores_val:.4f} time: {elapsed:.0f}s')
        mlflow.log_metric('Train_loss', avg_loss, epoch)
        mlflow.log_metric('Val_loss', avg_val_loss, epoch)
        mlflow.log_metric('Train_f1_weighted', f_scores_train, epoch)
        mlflow.log_metric('Val_f1_weighted', f_scores_val, epoch)
    time_elapsed = time.time() - since
    # Log best val f1 and register best model into mlflow repository
    mlflow.log_metric('Training_time',time_elapsed)
    mlflow.log_metric('Best_val_f1',best_f_scores)
    mlflow.log_metric('Best_epoch',best_epoch)
    mlflow.pytorch.log_model(best_model, "pytorch-model", registered_model_name="model_imdb")
    # Evaluate on test_dataset using the best model
    model = best_model
    avg_test_loss, test_preds, test_targets = test(test_dataloader, model, None)
    _, _, f_scores_test, _ = precision_recall_fscore_support(test_targets, test_preds, average = "weighted")
    # Log final test metric
    mlflow.log_metric('Final_test_f1',f_scores_test)
    logger.info(f'F1 Score Weighted on Test: {f_scores_test}')
    print(confusion_matrix(val_targets, val_preds))
