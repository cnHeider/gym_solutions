# coding=utf-8
import glob
import os
from itertools import count

import gym
import torch
from torch.autograd import Variable

import configs.default_config as configuration
from utilities.reinforment_learning.action import sample_action

_use_cuda = torch.cuda.is_available()
FloatTensor = torch.cuda.FloatTensor if _use_cuda else torch.FloatTensor


def testing_loop(model,
                 environment):

  print('-' * configuration.SPACER_SIZE)
  for i_episode in range(configuration.NUM_EPISODES):
    print('Episode {}/{}'.format(i_episode, configuration.NUM_EPISODES - 1))

    observations = environment.reset()  # Initial state

    state = FloatTensor([observations])

    for episode_frame_number in count():
      print('Frame {}'.format(episode_frame_number))
      environment.render()

      model_input = Variable(state, volatile=True).type(FloatTensor)
      action_probabilities = model(model_input)
      action_index = action_probabilities.data.max(1)[1].view(1, 1)
      observations, _, terminated, _ = environment.step(
          action_index[0, 0])
      state = FloatTensor([observations])

      if terminated:
        break

    print('-' * configuration.SPACER_SIZE)


def main():
  """

  """

  _environment = gym.make(configuration.GYM_ENVIRONMENT)

  _list_of_files = glob.glob(configuration.MODEL_DIRECTORY + '/*.model')
  _latest_model = max(_list_of_files, key=os.path.getctime)

  print('loading latest model: ' + _latest_model)

  _model = torch.load(_latest_model)

  if _use_cuda:
    _model = _model.cuda()

  testing_loop(_model, _environment)


if __name__ == '__main__':
  main()