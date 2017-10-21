import os
import math
import torch
import torch.nn as nn
import torch.optim as optim
import matplotlib.pyplot as plt
from tqdm import tqdm
import numpy as np
import argparse

from dataset import *
from constants import *
from util import *
from model import DeepJ
from generate import Generation

ce_loss = nn.CrossEntropyLoss()

def plot_loss(training_loss, validation_loss, name):
    # Draw graph
    plt.clf()
    plt.plot(training_loss)
    plt.plot(validation_loss)
    plt.savefig(OUT_DIR + '/' + name)

def train(model, train_generator, train_len, val_generator, val_len, plot=True, gen_rate=1, patience=5):
    """
    Trains a model on multiple seq batches by iterating through a generator.
    """
    # Number of training steps per epoch
    epoch = 1
    total_step = 1

    # Keep tracks of all losses in each epoch
    train_losses = []
    val_losses = []

    # Epoch loop
    while True:
        # Training
        step = 1
        total_loss = 0

        t_gen = train_generator()

        with tqdm(total=train_len) as t:
            t.set_description('Epoch {}'.format(epoch))

            for data in t_gen:
                teach_prob = max(MIN_SCHEDULE_PROB, 1 - SCHEDULE_RATE * total_step)
                loss = train_step(model, data, teach_prob)

                total_loss += loss
                avg_loss = total_loss / step
                t.set_postfix(loss=avg_loss, prob=teach_prob)
                t.update(BATCH_SIZE)

                step += 1
                total_step += 1

        train_losses.append(avg_loss)

        # Validation
        step = 1
        total_loss = 0

        v_gen = val_generator()

        with tqdm(total=val_len) as t:
            t.set_description('Validation {}'.format(epoch))

            for data in v_gen:
                loss = val_step(model, data)
                total_loss += loss
                avg_loss = total_loss / step
                t.set_postfix(loss=avg_loss)
                t.update(BATCH_SIZE)
                step += 1
            
        val_losses.append(avg_loss)

        if plot:
            plot_loss(train_losses, val_losses, 'loss.png')

        # Save model
        torch.save(model.state_dict(), OUT_DIR + '/model_' + str(epoch) + '.pt')

        # Generate
        if epoch % gen_rate == 0:
            print('Generating...')
            Generation(model).export(name='epoch_' + str(epoch))

        epoch += 1

        # Early stopping
        if epoch > patience:
            min_loss = min(val_losses)
            if min(val_losses[-patience:]) > min_loss:
                break

def train_step(model, data, teach_prob):
    """
    Trains the model on a single batch of sequence.
    """
    optimizer = optim.Adam(model.parameters())
    model.train()

    # Zero out the gradient
    optimizer.zero_grad()

    loss, avg_loss = compute_loss(model, data, teach_prob)

    loss.backward()
    optimizer.step()

    return avg_loss

def val_step(model, data):
    model.eval()
    return compute_loss(model, data, 1, volatile=True)[1]

def compute_loss(model, data, teach_prob, volatile=False):
    """
    Trains the model on a single batch of sequence.
    """
    # Convert all tensors into variables
    note_seq, styles = (var(d, volatile=volatile) for d in data)

    loss = 0
    seq_len = note_seq.size()[1]

    # Initialize hidden states
    states = None
    prev_note = note_seq[:, 0, :]
    
    # Iterate through the entire sequence
    for i in range(1, seq_len):
        target = note_seq[:, i]
        output, states = model(prev_note, styles, states)

        # Compute the loss.
        loss += ce_loss(output, torch.max(target, 1, keepdim=False)[1])

        # Choose note to feed based on coin flip (scheduled sampling)
        # TODO: Compare with and without scheduled sampling
        if np.random.random() <= teach_prob:
            prev_note = target
        else:
            # Apply softmax
            output = model.softmax(output)
            # Sample from the output
            prev_note = var(to_torch(batch_sample(output.cpu().data.numpy())))

    return loss, loss.data[0] / seq_len

def main():
    parser = argparse.ArgumentParser(description='Trains model')
    parser.add_argument('--path', help='Load existing model?')
    parser.add_argument('--gen', default=1, type=int, help='Generate per how many epochs?')
    parser.add_argument('--noplot', default=False, action='store_true', help='Do not plot training/loss graphs')
    args = parser.parse_args()

    print('=== Loading Model ===')
    print('GPU: {}'.format(torch.cuda.is_available()))
    model = DeepJ()

    if torch.cuda.is_available():
        model.cuda()

    if args.path:
        model.load_state_dict(torch.load(args.path))
        print('Restored model from checkpoint.')

    print()

    print('=== Dataset ===')
    os.makedirs(OUT_DIR, exist_ok=True)
    print('Loading data...')
    data = process(load())
    print()
    print('Creating data generators...')
    train_ind, val_ind = validation_split(iteration_indices(data))
    train_generator = lambda: batcher(sampler(data, train_ind))
    val_generator = lambda: batcher(sampler(data, val_ind))

    """
    # Checks if training data sounds right.
    for i, (train_seq, *_) in enumerate(train_generator()):
        write_file('train_seq_{}'.format(i), train_seq[0].cpu().data.numpy())
    """

    print('Training:', len(train_ind), 'Validation:', len(val_ind))
    print()

    print('=== Training ===')
    train(model, train_generator, len(train_ind), val_generator, \
         len(val_ind), plot=not args.noplot, gen_rate=args.gen)

if __name__ == '__main__':
    main()
