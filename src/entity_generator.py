from ast_nodes import *
from command_builder import CommandBuilder
from context import GeneratorContext
from my_types import *


class EntityGenerator:
    def __init__(self, ctx: GeneratorContext, builder: CommandBuilder):
        self.ctx = ctx
        self.builder = builder
        self.entity_schema = {
            'player': {
                'Health': FLOAT, 'MaxHealth': FLOAT, 'FoodLevel': INT, 'Air': INT,
                'Score': INT, 'Fire': INT, 'XpLevel': INT, 'XpTotal': INT,
                'PortalCooldown': INT, 'SleepTimer': INT, 'DeathTime': INT,
                'HurtTime': INT, 'HurtByTimestamp': INT,
                'Pos': TypeDesc('array', elem=FLOAT, shape=[3]),
                'Motion': TypeDesc('array', elem=FLOAT, shape=[3]),
                'Rotation': TypeDesc('array', elem=FLOAT, shape=[2]),
            },
            'zombie': {'Health': FLOAT, 'Fire': INT, 'Air': INT},
            'skeleton': {'Health': FLOAT, 'Fire': INT, 'Air': INT},
            'cow': {'Health': FLOAT, 'Fire': INT, 'Air': INT},
            'pig': {'Health': FLOAT, 'Fire': INT, 'Air': INT},
            'sheep': {'Health': FLOAT, 'Fire': INT, 'Air': INT},
            'chicken': {'Health': FLOAT, 'Fire': INT, 'Air': INT},
        }

    def gen_entity_read(self, expr: IndexExpr, target_var: str,
                        entity_var: str, field_name: str) -> List[str]:
        entity_subtype = getattr(expr.base._type, 'subtype', None)
        field_type = self._get_field_type(entity_subtype, field_name)

        if field_type and field_type.kind == 'prim' and field_type.name == 'int':
            scale = "1"
        else:
            scale = "100"

        return [f"execute store result score {target_var} _tmp run "
                f"data get entity {entity_var} {field_name} {scale}"]

    def gen_entity_write(self, target: IndexExpr, source_var: str,
                         entity_var: str, field_name: str) -> List[str]:
        entity_subtype = getattr(target.base._type, 'subtype', None)
        field_type = self._get_field_type(entity_subtype, field_name)

        if field_type and field_type.kind == 'prim' and field_type.name == 'int':
            store_type = "int"
            scale = "1"
        else:
            store_type = "float"
            scale = "0.01"

        return [f"execute store result entity {entity_var} {field_name} "
                f"{store_type} {scale} run scoreboard players get {source_var} _tmp"]

    def gen_entity_read_string(self, expr, target_storage: str,
                               entity_var: str, field_name: str) -> List[str]:
        """读取实体字符串NBT（如 CustomName）到 storage"""
        # Minecraft中生物名字存储在 CustomName，不是 Name
        # 如果 field_name 是 "Name"，实际NBT路径是 "CustomName"
        nbt_path = "CustomName" if field_name == "Name" else field_name
        return [f"data modify storage {self.ctx.namespace}:data {target_storage} "
                f"set from entity {entity_var} {nbt_path}"]

    def _get_field_type(self, subtype: Optional[str], field: str) -> Optional[TypeDesc]:
        if subtype and subtype in self.entity_schema:
            return self.entity_schema[subtype].get(field)
        if 'player' in self.entity_schema:
            return self.entity_schema['player'].get(field)
        return None

    def get_entity_selector(self, var_name: str) -> Optional[str]:
        storage, var_type = self.ctx.get_var(var_name)
        if var_type.kind != 'entity':
            return None
        if isinstance(storage, str) and storage.startswith('@'):
            return storage
        return None