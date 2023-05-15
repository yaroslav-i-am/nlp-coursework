import sys
from typing import Iterable, List
import dill
import os

import numpy as np
import pandas as pd

from sklearn.feature_extraction.text import CountVectorizer

from nltk.tokenize import WhitespaceTokenizer

import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from torch import nn
from torch.utils.data import Dataset, DataLoader
from tqdm.notebook import tqdm
from transformers import AutoModelForSequenceClassification, AutoTokenizer


class ReviewDataset(Dataset):
    def __init__(self, reviews, labels, tokenizer, max_model_input_length=512):
        self.reviews = reviews
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_model_input_length = max_model_input_length

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        review = self.reviews.iloc[idx]
        label = self.labels.iloc[idx]
        review_tokenized = self.tokenizer(
            review,
            add_special_tokens=True,
            max_length=self.max_model_input_length,
            padding='max_length',
            return_attention_mask=True,
            return_tensors='pt',
            truncation=True,
        )
        input_ids = review_tokenized['input_ids'].flatten()
        attn_mask = review_tokenized['attention_mask'].flatten()

        return {
            'review': review,
            'input_ids': input_ids,
            'attention_mask': attn_mask,
            'label': label,
        }


class BertClassifier:
    def __init__(self, checkpoint, n_classes=2):

        self.model = AutoModelForSequenceClassification.from_pretrained(checkpoint, local_files_only=False,
                                                                        ignore_mismatched_sizes=True)
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint)
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        self.max_len = self.model.config.max_position_embeddings
        self.out_features = self.model.config.pooler_fc_size
        self.model.classifier = torch.nn.Linear(self.out_features, n_classes)
        self.model.to(self.device)
        self.loss_fn = nn.CrossEntropyLoss()

        self.optimizer = torch.optim.Adam(self.model.classifier.parameters(), lr=1e-3)
        self.scheduler = torch.optim.lr_scheduler.StepLR(self.optimizer, step_size=1, gamma=0.5)

        self.all_losses = []
        self.epoch_losses = []
        self.epoch_acc = []

    def fit(self, train_dataloader: torch.utils.data.DataLoader):
        self.model.train()
        losses = []
        correct_predictions = 0

        t = tqdm(train_dataloader, file=sys.stdout, ncols=100)

        for data in t:
            input_ids = data['input_ids'].to(self.device)
            attention_mask = data['attention_mask'].to(self.device).to(float)
            labels = data['label'].to(self.device)

            outputs = self.model(
                input_ids=input_ids,
                attention_mask=attention_mask
            )

            preds = outputs.logits.argmax(dim=1)

            loss = self.loss_fn(outputs.logits, labels)

            correct_predictions += torch.sum(preds == labels)

            losses.append(loss.item())

            loss.backward()
            self.optimizer.step()
            self.optimizer.zero_grad()

            t.set_postfix(ordered_dict={'loss': loss.item()}, refresh=True)

        train_acc = correct_predictions.double() / len(train_dataloader.dataset)
        train_loss = np.mean(losses)
        self.all_losses.extend(losses)
        self.epoch_losses.append(train_loss)
        self.epoch_acc.append(train_acc)
        return train_acc, train_loss

    def evaluate(self, test_dataloader: DataLoader):
        self.model.eval()
        losses = []
        correct_predictions = 0

        all_preds = []
        all_labels = []

        t = tqdm(test_dataloader, file=sys.stdout, ncols=100)

        with torch.no_grad():
            for data in t:
                input_ids = data["input_ids"].to(self.device)
                attention_mask = data["attention_mask"].to(self.device)
                labels = data["label"].to(self.device)

                outputs = self.model(
                    input_ids=input_ids,
                    attention_mask=attention_mask
                )

                preds = torch.argmax(outputs.logits, dim=1)
                loss = self.loss_fn(outputs.logits, labels)
                correct_predictions += torch.sum(preds == labels)

                all_preds.extend(preds.tolist())
                all_labels.extend(labels)

                losses.append(loss.item())

                t.set_postfix(ordered_dict={'loss': loss.item()}, refresh=True)

        print('Classification report:')
        print(classification_report(test_dataloader.dataset.labels, all_preds))

        val_acc = correct_predictions.double() / len(test_dataloader.dataset)
        val_loss = np.mean(losses)
        return val_acc.item(), val_loss

    def train(self, n_epochs, pretrain_test=False):
        try:
            if pretrain_test:
                print('Pre-training test:')
                val_acc, val_loss = self.evaluate()
                print(f'Test loss {val_loss} accuracy {val_acc}')
                print('-' * 10)

            for epoch in range(n_epochs):
                print(f'Epoch {epoch + 1}/{n_epochs}')
                train_acc, train_loss = self.fit()
                print(f'Train loss {train_loss} accuracy {train_acc}')

                val_acc, val_loss = self.evaluate()
                print(f'Test loss {val_loss} accuracy {val_acc}')
                print('-' * 10)

                # self.scheduler.step()

        except KeyboardInterrupt:
            print('Training was manually stopped. ')


class BertLogRegClassifier:
    def __init__(self, checkpoint):

        self.model = AutoModelForSequenceClassification.from_pretrained(checkpoint)
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint)

        self.max_len = self.model.config.max_position_embeddings
        self.out_features = self.model.config.pooler_fc_size
        self.model.dropout = torch.nn.Sequential()
        self.model.classifier = torch.nn.Sequential()

        self.classifier = LogisticRegression(max_iter=2000, n_jobs=-1, random_state=42)

        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)

        self.all_train_embeddings = None
        self.all_test_embeddings = None

    def fit(self, train_dataloader: torch.utils.data.DataLoader):
        self.model.eval()

        self.all_train_embeddings = np.array([])
        all_preds = []

        t = tqdm(train_dataloader, file=sys.stdout, ncols=100)

        for data in t:
            with torch.no_grad():
                input_ids = data['input_ids'].to(self.device)
                attention_mask = data['attention_mask'].to(self.device).to(float)
                labels = data['label'].to(self.device)

                embeddings = self.model(
                    input_ids=input_ids,
                    attention_mask=attention_mask
                ).logits

                self.all_train_embeddings = np.append(self.all_train_embeddings, embeddings.cpu().numpy())
                all_preds.extend(labels)

        self.all_train_embeddings = self.all_train_embeddings.reshape(-1, self.out_features)

        self.classifier.fit(self.all_train_embeddings, all_preds)

    def predict(self, test_input):
        self.model.eval()

        self.all_test_embeddings = np.array([])

        t = tqdm(test_input, file=sys.stdout, ncols=100)

        for data in t:
            with torch.no_grad():
                input_ids = data['input_ids'].to(self.device)
                attention_mask = data['attention_mask'].to(self.device).to(float)

                embeddings = self.model(
                    input_ids=input_ids,
                    attention_mask=attention_mask
                ).logits

                self.all_test_embeddings = np.append(self.all_test_embeddings, embeddings.cpu().numpy())

        self.all_test_embeddings = self.all_test_embeddings.reshape(-1, self.out_features)

        return self.classifier.predict(self.all_test_embeddings)


class Pipeline:
    def __init__(self, task: str,
                 model=None,
                 preprocess=False,
                 model_type: str = 'linear',

                 ):
        import pandarallel
        pandarallel.pandarallel.initialize(nb_workers=os.cpu_count(), verbose=0)

        _task_types = ['classification', 'summarization']

        assert task in ['classification', 'summarization'], f'Wrong type of task. Expected: {_task_types}'

        self.task = task
        self.model = model
        self.preprocess = preprocess
        self.model_type = model_type
        self.vectorizer = None
        self.ret_value = None

    def classify(self, docs: Iterable[str], return_confs=False):
        NEGATIVE_THRESHOLD = 0.35

        if self.preprocess:
            # print('Preprocessing...')
            from src.nlp.preprocessing import clean
            if isinstance(docs, pd.Series) and os.cpu_count() > 1:
                docs = docs.parallel_apply(lambda doc: clean(doc, tokenizer_type='razdel', stopwords=[]))
            else:
                docs = list(map(lambda doc: clean(doc, tokenizer_type='razdel', stopwords=[]),
                                docs))

        # print('Vectorization...')

        if self.model_type == 'linear' and self.model is None:
            with open('models/logreg_tokrazdel_stopno_100k.model', 'rb') as f:
                self.model = dill.load(f)

            with open('models/count_vectorizer_1_4_100000.vocab', 'rb') as f:
                vocab = dill.load(f)
                self.vectorizer = CountVectorizer(tokenizer=WhitespaceTokenizer().tokenize,
                                                  vocabulary=vocab,
                                                  ngram_range=(1, 4))

        if self.model_type == 'lightgbm' and self.model is None:
            with open('models/lightgbm_tokrazdel_stopno_100k.model', 'rb') as f:
                self.model = dill.load(f)

            with open('models/lightgbm_count_vectorizer_1_4_100000.vocab', 'rb') as f:
                vocab = dill.load(f)
                self.vectorizer = CountVectorizer(tokenizer=WhitespaceTokenizer().tokenize,
                                                  vocabulary=vocab,
                                                  ngram_range=(1, 4))

        # print('Classification...')
        X_texts = self.vectorizer.transform(docs)

        if return_confs:
            if self.model_type == 'linear':
                self.ret_value = self.model.decision_function(X_texts)

        # probas = self.model.predict_proba(X_texts.astype(np.float64))
        # classes = np.where(probas > NEGATIVE_THRESHOLD, 0, 2)[:, 0]

        return self.model.predict(X_texts.astype(np.float64)), self.ret_value

    def __call__(self, docs: Iterable[str], return_confs=False, *args, **kwargs):
        if self.task == 'classification':
            return self.classify(docs=docs,
                                 return_confs=return_confs)


def get_df_by_person(data: pd.DataFrame, name: str) -> pd.DataFrame:
    filtered = data[data['ne'].str.contains(name, case=False)].sort_values(by='n_sents', ascending=False)
    return filtered


def get_df_by_film_and_person(data: pd.DataFrame, film_id: int, name: str) -> pd.DataFrame:
    df_with_person = get_df_by_person(data, name)
    filtered = df_with_person[df_with_person['film_id'] == film_id].sort_values(by='n_sents', ascending=False)
    return filtered


def collect_sents_to_summarize(data: pd.DataFrame, n_sents: int = 100) -> List[str]:
    all_sents = []
    for sents in data['occurrences']:
        all_sents.extend(sents)
    all_sents = np.array(all_sents)
    pl = Pipeline('classification', model_type='linear', preprocess=True)
    _, confs = pl(pd.Series(all_sents), return_confs=True)

    to_summarize = []
    to_summarize.extend(all_sents[confs < 0].tolist())
    _n = n_sents - len(to_summarize)
    _n = _n if _n < len(confs) else len(confs) - len(to_summarize)
    to_summarize.extend(all_sents[np.argpartition(confs, -_n)[-_n:]].tolist())

    return to_summarize


def split_opinions_to_chunks(tokenizer,
                             data: pd.DataFrame = None,
                             sentences: List[str] = None,
                             model_max_input: int = 600,
                             show_info: bool = False):
    if sentences is not None:
        all_sents = sentences
    elif data is not None:
        all_sents = list(data['occurrences'].sum())
    else:
        raise ValueError('No data is provided!')

    chunks = ['']
    chunks_length = [0]

    for sent in all_sents:
        _new_length = chunks_length[-1] + len(tokenizer.encode(sent))
        if _new_length > model_max_input:
            if len(tokenizer.encode(sent)) > model_max_input:
                print('The sentence has length greater that max model input, thus will be skipped', file=sys.stderr)
                continue
            chunks.append('')
            chunks_length.append(0)
            _new_length = chunks_length[-1] + len(tokenizer.encode(sent))

        chunks_length[-1] = _new_length
        chunks[-1] += ' ' + sent

    if show_info:
        import matplotlib.pyplot as plt

        print('Overall number of sentences:', len(all_sents))
        print('Number of chunks:', len(chunks))

        plt.figure(figsize=(10, 3))

        plt.plot(chunks_length)
        plt.title('The number of tokens across all chunks')
        plt.xlabel('Chunk number')
        plt.ylabel('Number of tokens')

        plt.show()

    return chunks
