# coding=utf-8
import time
from itertools import count

import gym
import torch
import torch.optim as optimisation
from visdom import Visdom

import configs.default_config as configuration
from architectures import MLP, CNN
from utilities.data.processing import gray_downscale
from utilities.persistence.model import save_model, load_model
from utilities.reinforment_learning.action import sample_action
from utilities.reinforment_learning.optimisation import optimise_model
from utilities.reinforment_learning.replay_memory import ReplayMemory
from utilities.visualisation import update_visualiser
from utilities.visualisation.moving_average import StatisticAggregator
from utilities.visualisation.visdom_manager import VisdomManager

_use_cuda = False
if configuration.USE_CUDA_IF_AVAILABLE:
  _use_cuda = torch.cuda.is_available()

FloatTensor = torch.cuda.FloatTensor if _use_cuda else torch.FloatTensor
LongTensor = torch.cuda.LongTensor if _use_cuda else torch.LongTensor
ByteTensor = torch.cuda.ByteTensor if _use_cuda else torch.ByteTensor
StateTensorType = FloatTensor
ActionTensorType = LongTensor

torch.manual_seed(configuration.RANDOM_SEED)

def training_loop(model,
                  target_model,
                  environment,
                  visualiser=None):
  """

  :param model:
  :param target_model:
  :param environment:
  :param visualiser:
  :return:
  """
  # Statistics
  visualisation_windows = {}

  total_steps_taken = 0
  episode_losses = StatisticAggregator(configuration.MOVING_AVERAGE_WINDOW)
  episode_rewards = StatisticAggregator(configuration.MOVING_AVERAGE_WINDOW)
  episode_durations = StatisticAggregator(configuration.MOVING_AVERAGE_WINDOW)
  memory = ReplayMemory(configuration.REPLAY_MEMORY_SIZE)

  optimiser = optimisation.RMSprop(model.parameters(),
                                   lr=configuration.LEARNING_RATE,
                                   eps=configuration.EPSILON,
                                   alpha=configuration.ALPHA)

  training_start_timestamp = time.time()
  print('-' * configuration.SPACER_SIZE)
  for episode_i in range(configuration.NUM_EPISODES):
    print('Episode {}/{} | Total steps taken {}'.format(episode_i,
                                         configuration.NUM_EPISODES - 1,
                                          total_steps_taken))

    episode_loss = 0
    episode_reward = 0

    observations = environment.reset()  # Initial state
    #state = gray_downscale(observations, _use_cuda)
    state = StateTensorType([observations])

    for episode_frame_number in count():
      if configuration.RENDER_ENVIRONMENT:
        environment.render()

      # Sample action based on the state from last iteration and take a step
      action = sample_action(environment,
                             model,
                             state,
                             configuration,
                             total_steps_taken)
      observations, reward, terminated, _ = environment.step(action[0, 0])

      if configuration.CLIP_REWARD:
        reward = max(-1.0, min(reward, 1.0)) # Reward clipping

      # Convert to tensors
      reward_tensor = FloatTensor([reward])
      non_terminal_tensor = ByteTensor([not terminated])

      # If environment terminated then there is no successor state
      successor_state = None
      if not terminated:
        #successor_state = gray_downscale(observations, _use_cuda)
        successor_state = StateTensorType([observations])

      memory.push(state, action, reward_tensor, successor_state, non_terminal_tensor)

      state = successor_state

      loss = 0
      if len(memory) >= configuration.BATCH_SIZE and \
            total_steps_taken > configuration.INITIAL_OBSERVATION_PERIOD and \
              total_steps_taken % configuration.LEARNING_FREQUENCY == 0:
        random_transitions = memory.sample(configuration.BATCH_SIZE)

        loss = optimise_model(model,
                                      target_model,
                                      optimiser,
                                      random_transitions,
                                      configuration,
                                      _use_cuda)

      total_steps_taken += 1
      episode_reward += reward
      episode_loss += loss

      # Update target model with the parameters of the learning model
      if total_steps_taken % configuration.SYNC_TARGET_MODEL_FREQUENCY == 0 \
          and configuration.DOUBLE_DQN:
        target_model.load_state_dict(model.state_dict())
        print('*** Target model synchronised ***')

      if episode_i % configuration.SAVE_MODEL_INTERVAL == 0:
        save_model(model, configuration)

      if terminated:
        if visualiser and configuration.USE_VISDOM:
          episode_length = episode_frame_number + 1

          episode_losses.append(episode_loss)
          episode_rewards.append(episode_reward)
          episode_durations.append(episode_length)

          rgb_array = environment.render(mode='rgb_array')

          visualisation_windows = update_visualiser(
              visualiser,
              episode_i,
              episode_loss / episode_length,
              episode_losses.moving_average(configuration.MOVING_AVERAGE_WINDOW),
              episode_reward / episode_length,
              episode_rewards.moving_average(configuration.MOVING_AVERAGE_WINDOW),
              episode_length,
              episode_durations.moving_average(configuration.MOVING_AVERAGE_WINDOW),
              rgb_array.swapaxes(0, 2).swapaxes(1, 2),
              visualisation_windows,
              configuration)
        print('Episode terminated')
        break

    print('-' * configuration.SPACER_SIZE)

    if episode_rewards.moving_average(configuration.MOVING_AVERAGE_WINDOW) \
        >= configuration.SOLVED_REWARD:
      break

  time_elapsed = time.time() - training_start_timestamp
  print('Training done, time elapsed: {:.0f}m {:.0f}s'.format(
      time_elapsed // configuration.SECONDS_IN_A_MINUTE,
      time_elapsed % configuration.SECONDS_IN_A_MINUTE))

  return model # or target_model


def main():
  """

  :return:
  """
  _visualiser = None
  if configuration.USE_VISDOM:
    _visualiser = Visdom(configuration.VISDOM_SERVER)

  _environment = gym.make(configuration.GYM_ENVIRONMENT)
  _environment.seed(configuration.RANDOM_SEED)

  # (coord_x, coord_y, vel_x, vel_y, angle, angular_vel, l_leg_on_ground, r_leg_on_ground)
  if configuration.ARCHITECTURE_CONFIGURATION['input_size'] < 0:
    configuration.ARCHITECTURE_CONFIGURATION['input_size'] = \
      _environment.observation_space.shape
  print('observation dimensions: ', configuration.ARCHITECTURE_CONFIGURATION['input_size'])

  if   configuration.ARCHITECTURE_CONFIGURATION[
    'output_size'] < 0:
    configuration.ARCHITECTURE_CONFIGURATION['output_size'] = \
      _environment.action_space.n
  print('action dimensions: ', configuration.ARCHITECTURE_CONFIGURATION['output_size'])

  _model = MLP(configuration.ARCHITECTURE_CONFIGURATION)
  #_model = CNN(configuration.ARCHITECTURE_CONFIGURATION)
  if configuration.LOAD_PREVIOUS_MODEL_IF_AVAILABLE:
    _model = load_model(configuration)
  _target_model = MLP(configuration.ARCHITECTURE_CONFIGURATION)
  #_target_model = CNN(configuration.ARCHITECTURE_CONFIGURATION)
  _target_model.load_state_dict(_model.state_dict())

  if _use_cuda:
    _model = _model.cuda()
    _target_model.cuda()

  _trained_model = training_loop(_model,
                                _target_model,
                                _environment,
                                _visualiser)

  _environment.render(close=True)
  _environment.close()

  save_model(_trained_model, configuration)

if __name__ == '__main__':
  VISDOM_MANAGER = VisdomManager()
  VISDOM_MANAGER.start_visdom_process(configuration)

  main()

  VISDOM_MANAGER.stop_visdom_process()
