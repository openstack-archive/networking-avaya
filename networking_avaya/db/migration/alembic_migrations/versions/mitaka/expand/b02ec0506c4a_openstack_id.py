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
Revision ID: b02ec0506c4a
Revises: c10be324e57f
Create Date: 2016-11-25 20:07:41.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b02ec0506c4a'
down_revision = 'c10be324e57f'


def upgrade():
    op.create_table(
        'avaya_openstack_id',
        sa.Column('id', sa.String(255), primary_key=True),
    )
