# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Provides the web interface for editing anomaly threshold configurations."""
from __future__ import print_function
from __future__ import division
from __future__ import absolute_import

import json

from dashboard import edit_config_handler
from dashboard.common import request_handler
from dashboard.models import anomaly_config


class EditAnomalyConfigsHandler(edit_config_handler.EditConfigHandler):
  """Handles editing the info about anomaly threshold configurations.

  The post method is inherited from EditConfigHandler. It takes the request
  parameters documented there, as well as the following parameter, which
  is a property of AnomalyConfig:
    config: A JSON dictionary mapping config parameters to values.
  """

  def __init__(self, request, response):
    # TODO(https://crbug.com/1262292): Change to super() after Python2 trybots retire.
    # pylint: disable=super-with-arguments
    super(EditAnomalyConfigsHandler,
          self).__init__(request, response, anomaly_config.AnomalyConfig)

  def get(self):
    """Renders the UI with the form."""

    # Note, this is similar to edit_sheriffs, and there may be some common
    # logic that oculd be extracted to EditConfigHandler.
    def ConfigData(config):
      return {
          'config': json.dumps(config.config, indent=2, sort_keys=True),
          'patterns': '\n'.join(sorted(config.patterns)),
      }

    anomaly_configs = {
        config.key.string_id(): ConfigData(config)
        for config in anomaly_config.AnomalyConfig.query()
    }

    self.RenderHtml(
        'edit_anomaly_configs.html', {
            'anomaly_config_json': json.dumps(anomaly_configs),
            'anomaly_config_names': sorted(anomaly_configs.keys()),
        })

  def _UpdateFromRequestParameters(self, entity):
    """Updates the given AnomalyConfig based on query parameters."""
    # This overrides the method in the superclass.
    entity.config = self._GetAndValidateConfigContents()

  def _GetAndValidateConfigContents(self):
    """Returns a config dict if one could be gotten, or None otherwise."""
    config = self.request.get('config')
    if not config:
      raise request_handler.InvalidInputError('No config contents given.')
    try:
      config_dict = json.loads(config)
    except (ValueError, TypeError) as json_parse_error:
      raise request_handler.InvalidInputError(str(json_parse_error))
    if not isinstance(config_dict, dict):
      raise request_handler.InvalidInputError('Config was not a dict.')
    return config_dict
