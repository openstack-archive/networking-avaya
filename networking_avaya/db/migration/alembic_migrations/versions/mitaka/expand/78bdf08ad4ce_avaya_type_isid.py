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

"""Avaya ML2 I-SID type driver
Revision ID: 78bdf08ad4ce
Revises: f5241c762eb6
Create Date: 2016-09-21 13:00:41.000000
"""

from alembic import op
import sqlalchemy as sa

from neutron.db.migration import cli

# revision identifiers, used by Alembic.
revision = '78bdf08ad4ce'
down_revision = 'f5241c762eb6'
branch_labels = (cli.EXPAND_BRANCH,)


def upgrade():
    op.create_table(
        'avaya_isid_allocations',
        sa.Column('isid', sa.Integer(), autoincrement=False,
                  nullable=False),
        sa.Column('allocated', sa.Boolean(), nullable=False,
                  server_default=sa.sql.false(), index=True),
        sa.PrimaryKeyConstraint('isid'))
