from my_types import *

# 实体属性 Schema
DEFAULT_ENTITY_SCHEMA = {
    'player': {
        'Health': FLOAT, 'MaxHealth': FLOAT, 'FoodLevel': INT, 'Air': INT,
        'Score': INT, 'Name': STRING, 'XpLevel': INT, 'XpTotal': INT,
        'OnGround': BOOL, 'Fire': INT, 'Saturation': INT, 'Armor': INT,
        'Pos': TypeDesc('array', elem=FLOAT, shape=[3]),
    },
    'zombie': {'Health': FLOAT, 'Attack': INT, 'Name': STRING, 'OnGround': BOOL, 'Fire': INT},
    'skeleton': {'Health': FLOAT, 'Attack': INT, 'Name': STRING, 'OnGround': BOOL, 'Fire': INT},
    'cow': {'Health': FLOAT, 'Name': STRING, 'OnGround': BOOL, 'Fire': INT},
    'pig': {'Health': FLOAT, 'Name': STRING, 'OnGround': BOOL, 'Fire': INT},
    'sheep': {'Health': FLOAT, 'Name': STRING, 'OnGround': BOOL, 'Fire': INT, 'Color': INT},
    'chicken': {'Health': FLOAT, 'Name': STRING, 'OnGround': BOOL, 'Fire': INT, 'Flying': BOOL},
}

def get_entity_schema(entity_type: str) -> dict:
    """获取实体类型对应的属性表"""
    return DEFAULT_ENTITY_SCHEMA.get(entity_type, {})

def is_valid_entity_field(entity_type: str, field: str) -> bool:
    """检查字段是否对实体类型有效"""
    schema = get_entity_schema(entity_type)
    return field in schema