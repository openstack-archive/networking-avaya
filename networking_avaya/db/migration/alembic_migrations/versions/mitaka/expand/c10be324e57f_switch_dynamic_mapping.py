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

"""Avaya Switch Dynamic Mapping
Revision ID: c10be324e57f
Revises: 88ac6f7d8899
Create Date: 2016-10-13 13:43:41.000000
"""

from alembic import op
import sqlalchemy as sa

from neutron.db import sqlalchemytypes


# revision identifiers, used by Alembic.
revision = 'c10be324e57f'
down_revision = '88ac6f7d8899'


def upgrade():
    op.create_table(
        'avaya_switch_dynamic_mappings',
        sa.Column('switch', sa.String(255), nullable=False),
        sa.Column('port', sa.String(255), nullable=False),
        sa.Column('host', sa.String(255), nullable=False, index=True),
        sa.Column('physnet', sa.String(255), nullable=False),
        sa.Column('last_update', sqlalchemytypes.TruncatedDateTime,
                  nullable=False),
        sa.PrimaryKeyConstraint('switch', 'port'),
    )
