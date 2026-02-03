from ply import lex

reserved = {
    'let': 'LET',
    'struct': 'STRUCT',
    'for': 'FOR',
    'in': 'IN',
    'while': 'WHILE',
    'if': 'IF',
    'else': 'ELSE',
    'int': 'INT_TYPE',
    'string': 'STRING_TYPE',
    'true': 'TRUE',
    'false': 'FALSE',
    'fn': 'FN',
    'return': 'RETURN',
    'cmd': 'CMD',
    'condition': 'CONDITION',
    'entity': 'ENTITY',
    'tag': 'TAG',
    'loot': 'LOOT',
    'import': 'IMPORT',
    'from': 'FROM',
}

tokens = [
    'IDENT', 'INT', 'FLOAT', 'STRING', 'SELECTOR',
    'DOT',
    'DOTDOT',
    'PLUS', 'MINUS', 'TIMES', 'DIV',
    'ARROW',
    'LT', 'GT', 'LE', 'GE', 'EQ', 'NE',
    'DOLLAR',
    'UMINUS',
] + list(set(reserved.values()))

t_DOLLAR = r'\$'
t_DOT = r'\.'
literals = ['=', ':', '{', '}', '[', ']', ',', '(', ')']

t_LE = r'<='
t_GE = r'>='
t_EQ = r'=='
t_NE = r'!='
t_LT = r'<'
t_GT = r'>'

t_DOTDOT = r'\.\.'
t_PLUS = r'\+'
t_MINUS = r'-'
t_TIMES = r'\*'
t_DIV = r'/'
t_ARROW = r'->'

def t_SELECTOR(t):
    r'@[A-Za-z_]\w*(?:\[[^\]]*\])?'
    return t

def t_TRIPLE_STRING(t):
    r'"""[\s\S]*?"""'
    s = t.value[3:-3]
    s = s.replace('\\"', '"').replace('\\\\', '\\').replace('\\n', '\n').replace('\\t', '\t')
    t.value = s
    t.type = 'STRING'
    return t

def t_STRING(t):
    r'"([^"\\]|\\.)*"'
    s = t.value[1:-1]
    s = s.replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\').replace('\\"', '"')
    t.value = s
    return t

def t_FLOAT(t):
    r'\d+\.\d+'
    t.value = float(t.value)
    return t

def t_INT(t):
    r'\d+'
    t.value = int(t.value)
    return t

def t_IDENT(t):
    r'[A-Za-z_]\w*'
    t.type = reserved.get(t.value, 'IDENT')
    return t

t_ignore = ' \t\r'

def t_newline(t):
    r'\n+'
    t.lexer.lineno += t.value.count('\n')

def t_comment(t):
    r'//[^\n]*'
    pass

def t_multiline_comment(t):
    r'/\*(.|\n)*?\*/'
    t.lexer.lineno += t.value.count('\n')
    pass

def t_error(t):
    print(f"Illegal character {t.value[0]!r} at line {t.lineno}")
    t.lexer.skip(1)

lexer = lex.lex()