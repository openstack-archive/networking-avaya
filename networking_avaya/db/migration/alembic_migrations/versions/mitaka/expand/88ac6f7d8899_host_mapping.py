# Copyright (c) 2016 Avaya, Inc
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

"""Avaya Host/Network Mapping
Revision ID: 88ac6f7d8899
Revises: 78bdf08ad4ce
Create Date: 2016-10-20 18:13:41.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '88ac6f7d8899'
down_revision = '78bdf08ad4ce'


def upgrade():
    op.create_table(
        'avaya_host_network_mappings',
        sa.Column('host', sa.String(255), nullable=False),
        sa.Column('network_id', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('tx_id', sa.String(36), nullable=True, unique=True),
        sa.PrimaryKeyConstraint('host', 'network_id'),
    )
