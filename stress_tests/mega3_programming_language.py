#!/usr/bin/env python3
"""Mega Tier 13: Programming Language Ecosystem.

Complexity: 120-180 workers, ~350 files, ~25K LOC.
Task: Build a complete programming language ecosystem with lexer, parser (recursive
descent), AST, type checker, IR generator, bytecode compiler, VM, garbage collector,
standard library, REPL, error reporting, source maps, module system, package manager,
formatter, linter, LSP stub, test framework, documentation generator, and debugger.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-mega-3"
WORKER_TIMEOUT = 1500

SCAFFOLD_FILES = {
    "lumina/__init__.py": '''\
"""Lumina — A complete programming language ecosystem in pure Python."""

__version__ = "0.1.0"
__language__ = "lumina"

from lumina.lexer.token import Token, TokenType
from lumina.ast.nodes import ASTNode

__all__ = ["Token", "TokenType", "ASTNode"]
''',
    "lumina/lexer/__init__.py": '''\
"""Lexer package for tokenizing Lumina source code."""

from lumina.lexer.token import Token, TokenType
from lumina.lexer.lexer import Lexer

__all__ = ["Token", "TokenType", "Lexer"]
''',
    "lumina/lexer/token.py": '''\
"""Token definitions for the Lumina lexer."""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class TokenType(Enum):
    # Literals
    NUMBER = auto()
    STRING = auto()
    BOOL = auto()
    NIL = auto()
    
    # Identifiers
    IDENTIFIER = auto()
    
    # Keywords
    AND = auto()
    OR = auto()
    NOT = auto()
    IF = auto()
    ELSE = auto()
    ELIF = auto()
    WHILE = auto()
    FOR = auto()
    IN = auto()
    BREAK = auto()
    CONTINUE = auto()
    RETURN = auto()
    FUN = auto()
    CLASS = auto()
    EXTENDS = auto()
    THIS = auto()
    SUPER = auto()
    VAR = auto()
    VAL = auto()
    CONST = auto()
    IMPORT = auto()
    FROM = auto()
    AS = auto()
    TRY = auto()
    CATCH = auto()
    FINALLY = auto()
    THROW = auto()
    TYPE = auto()
    INTERFACE = auto()
    IMPLEMENTS = auto()
    PUBLIC = auto()
    PRIVATE = auto()
    PROTECTED = auto()
    STATIC = auto()
    ABSTRACT = auto()
    OVERRIDE = auto()
    NATIVE = auto()
    
    # Operators
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    DOUBLE_STAR = auto()
    
    # Comparison
    EQUAL = auto()
    NOT_EQUAL = auto()
    LESS = auto()
    LESS_EQUAL = auto()
    GREATER = auto()
    GREATER_EQUAL = auto()
    
    # Assignment
    ASSIGN = auto()
    PLUS_ASSIGN = auto()
    MINUS_ASSIGN = auto()
    STAR_ASSIGN = auto()
    SLASH_ASSIGN = auto()
    
    # Logical
    LOGICAL_AND = auto()
    LOGICAL_OR = auto()
    LOGICAL_NOT = auto()
    
    # Bitwise
    BITWISE_AND = auto()
    BITWISE_OR = auto()
    BITWISE_XOR = auto()
    BITWISE_NOT = auto()
    LEFT_SHIFT = auto()
    RIGHT_SHIFT = auto()
    
    # Increment/Decrement
    INCREMENT = auto()
    DECREMENT = auto()
    
    # Delimiters
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    
    # Punctuation
    COMMA = auto()
    DOT = auto()
    COLON = auto()
    SEMICOLON = auto()
    ARROW = auto()
    FAT_ARROW = auto()
    QUESTION = auto()
    QUESTION_DOT = auto()
    QUESTION_QUESTION = auto()
    ELLIPSIS = auto()
    AT = auto()
    HASH = auto()
    BACKTICK = auto()
    
    # Special
    NEWLINE = auto()
    INDENT = auto()
    DEDENT = auto()
    EOF = auto()
    COMMENT = auto()
    WHITESPACE = auto()


@dataclass(frozen=True)
class Token:
    """A token in the source code."""
    type: TokenType
    value: Any
    line: int
    column: int
    file: str = ""
    
    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.column})"
    
    def is_keyword(self) -> bool:
        keywords = {
            TokenType.AND, TokenType.OR, TokenType.NOT, TokenType.IF, TokenType.ELSE,
            TokenType.ELIF, TokenType.WHILE, TokenType.FOR, TokenType.IN, TokenType.BREAK,
            TokenType.CONTINUE, TokenType.RETURN, TokenType.FUN, TokenType.CLASS,
            TokenType.THIS, TokenType.SUPER, TokenType.VAR, TokenType.VAL, TokenType.CONST,
            TokenType.IMPORT, TokenType.FROM, TokenType.AS, TokenType.TRY, TokenType.CATCH,
            TokenType.TYPE, TokenType.INTERFACE, TokenType.PUBLIC, TokenType.PRIVATE,
        }
        return self.type in keywords
''',
    "lumina/ast/__init__.py": '''\
"""Abstract Syntax Tree nodes for Lumina."""

from lumina.ast.nodes import ASTNode, Program, FunctionDecl, ClassDecl

__all__ = ["ASTNode", "Program", "FunctionDecl", "ClassDecl"]
''',
    "lumina/ast/nodes.py": '''\
"""AST node definitions for Lumina."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class ASTNode(ABC):
    """Base class for all AST nodes."""
    line: int = 0
    column: int = 0
    
    @abstractmethod
    def accept(self, visitor: "ASTVisitor") -> Any:
        pass
    
    def get_children(self) -> list["ASTNode"]:
        return []


@dataclass
class Program(ASTNode):
    """Root node representing a complete program."""
    statements: list[ASTNode] = field(default_factory=list)
    file_path: str = ""
    
    def accept(self, visitor: "ASTVisitor") -> Any:
        return visitor.visit_program(self)
    
    def get_children(self) -> list[ASTNode]:
        return self.statements


@dataclass
class FunctionDecl(ASTNode):
    """Function declaration node."""
    name: str = ""
    params: list["Parameter"] = field(default_factory=list)
    return_type: "TypeAnnotation | None" = None
    body: "Block | None" = None
    is_static: bool = False
    is_native: bool = False
    visibility: str = "public"
    
    def accept(self, visitor: "ASTVisitor") -> Any:
        return visitor.visit_function_decl(self)
    
    def get_children(self) -> list[ASTNode]:
        children = []
        if self.return_type:
            children.append(self.return_type)
        if self.body:
            children.append(self.body)
        return children + self.params


@dataclass
class ClassDecl(ASTNode):
    """Class declaration node."""
    name: str = ""
    super_class: str | None = None
    interfaces: list[str] = field(default_factory=list)
    members: list[ASTNode] = field(default_factory=list)
    is_abstract: bool = False
    visibility: str = "public"
    
    def accept(self, visitor: "ASTVisitor") -> Any:
        return visitor.visit_class_decl(self)
    
    def get_children(self) -> list[ASTNode]:
        return self.members
''',
    "tests/__init__.py": "",
    "tests/conftest.py": """\
import pytest
from lumina.lexer.token import Token, TokenType
from lumina.lexer.lexer import Lexer
from lumina.ast.nodes import Program, FunctionDecl


@pytest.fixture
def sample_token():
    return Token(TokenType.NUMBER, 42, 1, 1, "test.lum")


@pytest.fixture
def sample_lexer():
    return Lexer(source="let x = 42", file_path="test.lum")


@pytest.fixture
def sample_program():
    return Program(statements=[], file_path="test.lum")
""",
    "tests/test_token.py": """\
from lumina.lexer.token import Token, TokenType


def test_token_creation():
    token = Token(TokenType.NUMBER, 42, 1, 5)
    assert token.type == TokenType.NUMBER
    assert token.value == 42
    assert token.line == 1
    assert token.column == 5


def test_token_is_keyword():
    token_if = Token(TokenType.IF, "if", 1, 1)
    token_num = Token(TokenType.NUMBER, 42, 1, 1)
    assert token_if.is_keyword()
    assert not token_num.is_keyword()


def test_token_repr():
    token = Token(TokenType.IDENTIFIER, "foo", 2, 3)
    repr_str = repr(token)
    assert "IDENTIFIER" in repr_str
    assert "foo" in repr_str
    assert "2:3" in repr_str
""",
    "tests/test_ast_nodes.py": """\
from lumina.ast.nodes import Program, FunctionDecl, ClassDecl


def test_program_creation():
    prog = Program(statements=[], file_path="test.lum")
    assert prog.statements == []
    assert prog.file_path == "test.lum"


def test_function_decl_creation():
    func = FunctionDecl(name="foo", params=[], is_static=False)
    assert func.name == "foo"
    assert func.params == []
    assert not func.is_static


def test_class_decl_creation():
    cls = ClassDecl(name="MyClass", super_class="Base", is_abstract=False)
    assert cls.name == "MyClass"
    assert cls.super_class == "Base"
    assert not cls.is_abstract
""",
}

INSTRUCTIONS = """\
Build a COMPLETE PROGRAMMING LANGUAGE ECOSYSTEM called "lumina". Use ONLY Python stdlib.
No external dependencies. This is a full-featured language with lexer, parser, AST,
type checker, IR, bytecode compiler, VM, garbage collector, stdlib, REPL, LSP stub,
package manager, formatter, linter, test framework, docs generator, and debugger.

=== SUBSYSTEM: Lexer ===

MODULE 1 — Lexer Core (`lumina/lexer/`):

1. Create `lumina/lexer/lexer.py`:
   - `Lexer` class:
     - `__init__(self, source: str, file_path: str = "")`
     - `source: str`, `file_path: str`, `tokens: list[Token]`
     - `pos: int = 0`, `line: int = 1`, `column: int = 1`
     - `indent_stack: list[int] = [0]` — for Python-style indentation
     - `tokenize(self) -> list[Token]` — main entry point
     - `scan_token(self) -> Token | None` — scan next token
     - `advance(self) -> str` — consume and return current char
     - `peek(self, offset: int = 0) -> str` — look ahead without consuming
     - `match(self, expected: str) -> bool` — consume if matches
     - `skip_whitespace(self) -> None` — skip spaces/tabs
     - `skip_comment(self) -> None` — skip // and /* */ comments
     - `read_string(self, quote: str) -> Token` — handle "string" and 'string' with escape sequences
     - `read_number(self) -> Token` — integers, floats, scientific notation (1e10, 2.5e-3)
     - `read_identifier(self) -> Token` — identifiers and keywords
     - `handle_indentation(self) -> list[Token]` — emit INDENT/DEDENT tokens
     - `is_at_end(self) -> bool`
     - `error(self, message: str) -> LexerError`
   - `KEYWORDS: dict[str, TokenType]` mapping

2. Create `lumina/lexer/errors.py`:
   - `LexerError` exception with message, line, column, file
   - `LexerWarning` for non-fatal issues
   - `format_error(error: LexerError) -> str` — human-readable format

MODULE 2 — Source Management (`lumina/source/`):

3. Create `lumina/source/location.py`:
   - `SourceLocation` dataclass: file, line, column, offset
   - `merge_locations(start: SourceLocation, end: SourceLocation) -> SourceLocation`

4. Create `lumina/source/span.py`:
   - `SourceSpan` dataclass: start (SourceLocation), end (SourceLocation)
   - `contains(self, other: SourceSpan) -> bool`
   - `merge(self, other: SourceSpan) -> SourceSpan`

=== SUBSYSTEM: Parser ===

MODULE 3 — AST Nodes (`lumina/ast/`):

5. Create `lumina/ast/visitor.py`:
   - `ASTVisitor` base class with visit methods for all node types:
     - `visit_program(self, node: Program) -> Any`
     - `visit_function_decl(self, node: FunctionDecl) -> Any`
     - `visit_class_decl(self, node: ClassDecl) -> Any`
     - `visit_var_decl(self, node: VarDecl) -> Any`
     - `visit_block(self, node: Block) -> Any`
     - `visit_if(self, node: If) -> Any`
     - `visit_while(self, node: While) -> Any`
     - `visit_for(self, node: For) -> Any`
     - `visit_return(self, node: Return) -> Any`
     - `visit_expression_stmt(self, node: ExpressionStmt) -> Any`
     - `visit_binary_op(self, node: BinaryOp) -> Any`
     - `visit_unary_op(self, node: UnaryOp) -> Any`
     - `visit_literal(self, node: Literal) -> Any`
     - `visit_identifier(self, node: Identifier) -> Any`
     - `visit_assignment(self, node: Assignment) -> Any`
     - `visit_call(self, node: Call) -> Any`
     - `visit_member_access(self, node: MemberAccess) -> Any`
     - `visit_index_access(self, node: IndexAccess) -> Any`
     - `visit_this(self, node: This) -> Any`
     - `visit_super(self, node: Super) -> Any`
     - `visit_try(self, node: Try) -> Any`
     - `visit_throw(self, node: Throw) -> Any`
   - Each method raises NotImplementedError by default

6. Create `lumina/ast/expressions.py`:
   - `BinaryOp` dataclass: left, operator, right
   - `UnaryOp` dataclass: operator, operand
   - `Literal` dataclass: value (int, float, str, bool, None)
   - `Identifier` dataclass: name
   - `Assignment` dataclass: target, value
   - `CompoundAssignment` dataclass: target, operator, value (+-=, etc.)
   - `Call` dataclass: callee, arguments (list[ASTNode])
   - `MemberAccess` dataclass: object, member_name
   - `IndexAccess` dataclass: object, index
   - `TernaryOp` dataclass: condition, true_expr, false_expr
   - `NullCoalesce` dataclass: left, right (?? operator)
   - `LambdaExpr` dataclass: params, body
   - `ListLiteral` dataclass: elements
   - `DictLiteral` dataclass: pairs (key, value)
   - `This`, `Super` singleton nodes
   - All inherit from ASTNode with accept() methods

7. Create `lumina/ast/statements.py`:
   - `ExpressionStmt` dataclass: expression
   - `VarDecl` dataclass: name, type_annotation, initializer, is_const, is_val
   - `Block` dataclass: statements
   - `If` dataclass: condition, then_branch, else_branch (optional elif chain)
   - `While` dataclass: condition, body
   - `For` dataclass: iterator_var, iterable, body
   - `Return` dataclass: value (optional)
   - `Break`, `Continue` nodes
   - `Throw` dataclass: exception
   - `Try` dataclass: try_block, catch_clauses, finally_block
   - `CatchClause` dataclass: exception_var, exception_type, block
   - `ImportDecl` dataclass: module_path, import_name, alias
   - `TypeAnnotation` dataclass: type_name, is_optional, is_array

8. Create `lumina/ast/declarations.py`:
   - `Parameter` dataclass: name, type_annotation, default_value, is_vararg
   - `InterfaceDecl` dataclass: name, methods (list of method signatures)
   - `MethodSignature` dataclass: name, params, return_type
   - `EnumDecl` dataclass: name, variants
   - `EnumVariant` dataclass: name, associated_values
   - `PropertyDecl` dataclass: name, type, getter, setter, is_static
   - `ConstructorDecl` dataclass: params, body, visibility
   - `DestructorDecl` dataclass: body

9. Create `lumina/ast/printer.py`:
   - `ASTPrinter(ASTVisitor)` — pretty print AST as tree
   - `print(self, node: ASTNode) -> str`
   - Indentation-based tree formatting

MODULE 4 — Parser (`lumina/parser/`):

10. Create `lumina/parser/parser.py`:
    - `Parser` class (recursive descent):
      - `__init__(self, tokens: list[Token])`
      - `tokens: list[Token]`, `pos: int = 0`
      - `parse(self) -> Program` — entry point
      - `parse_program(self) -> Program`
      - `parse_declaration(self) -> ASTNode` — top-level decl
      - `parse_function_decl(self) -> FunctionDecl`
      - `parse_class_decl(self) -> ClassDecl`
      - `parse_var_decl(self) -> VarDecl`
      - `parse_statement(self) -> ASTNode`
      - `parse_if(self) -> If`
      - `parse_while(self) -> While`
      - `parse_for(self) -> For`
      - `parse_return(self) -> Return`
      - `parse_block(self) -> Block`
      - `parse_expression(self) -> ASTNode` — lowest precedence
      - `parse_assignment(self) -> ASTNode`
      - `parse_ternary(self) -> ASTNode`
      - `parse_or(self) -> ASTNode`
      - `parse_and(self) -> ASTNode`
      - `parse_equality(self) -> ASTNode`
      - `parse_comparison(self) -> ASTNode`
      - `parse_term(self) -> ASTNode`
      - `parse_factor(self) -> ASTNode`
      - `parse_unary(self) -> ASTNode`
      - `parse_postfix(self) -> ASTNode`
      - `parse_primary(self) -> ASTNode`
      - `parse_call(self, callee: ASTNode) -> Call`
      - `parse_member_access(self, obj: ASTNode) -> MemberAccess`
      - `parse_index_access(self, obj: ASTNode) -> IndexAccess`
      - `parse_parameters(self) -> list[Parameter]`
      - `parse_arguments(self) -> list[ASTNode]`
      - `parse_type_annotation(self) -> TypeAnnotation`
      - `current(self) -> Token` — current token
      - `peek(self, offset: int = 0) -> Token`
      - `advance(self) -> Token`
      - `check(self, type: TokenType) -> bool`
      - `match(self, *types: TokenType) -> bool`
      - `consume(self, type: TokenType, message: str) -> Token`
      - `is_at_end(self) -> bool`
      - `synchronize(self) -> None` — error recovery
      - `error(self, message: str) -> ParseError`

11. Create `lumina/parser/errors.py`:
    - `ParseError` exception with token, message
    - `ParseWarning` for non-fatal issues
    - `format_parse_error(error: ParseError) -> str`

12. Create `lumina/parser/precedence.py`:
    - `Precedence` enum: NONE, ASSIGNMENT, TERNARY, OR, AND, EQUALITY, COMPARISON, TERM, FACTOR, UNARY, POSTFIX, CALL, PRIMARY
    - `get_precedence(operator: TokenType) -> Precedence`

=== SUBSYSTEM: Type System ===

MODULE 5 — Type System (`lumina/types/`):

13. Create `lumina/types/base.py`:
    - `LuminaType` base class:
      - `name: str`
      - `is_optional: bool = False`
      - `__eq__(self, other) -> bool`
      - `is_assignable_from(self, other: LuminaType) -> bool`
      - `to_string(self) -> str`

14. Create `lumina/types/primitives.py`:
    - `IntType(LuminaType)`, `FloatType(LuminaType)`, `BoolType(LuminaType)`, `StringType(LuminaType)`, `NilType(LuminaType)`
    - `AnyType(LuminaType)` — dynamic typing escape hatch

15. Create `lumina/types/composite.py`:
    - `FunctionType(LuminaType)`: param_types, return_type
    - `ClassType(LuminaType)`: name, super_type, members
    - `InterfaceType(LuminaType)`: name, methods
    - `ListType(LuminaType)`: element_type
    - `DictType(LuminaType)`: key_type, value_type
    - `UnionType(LuminaType)`: types list
    - `OptionalType(LuminaType)`: inner_type

MODULE 6 — Type Checker (`lumina/typechecker/`):

16. Create `lumina/typechecker/checker.py`:
    - `TypeChecker(ASTVisitor)`:
      - `__init__(self)`
      - `errors: list[TypeError]`
      - `symbol_table: SymbolTable`
      - `current_function_return_type: LuminaType | None`
      - `check(self, program: Program) -> list[TypeError]`
      - `visit_function_decl(self, node) -> None` — check body against return type
      - `visit_var_decl(self, node) -> None` — check type consistency
      - `visit_if(self, node) -> None` — condition must be bool
      - `visit_while(self, node) -> None`
      - `visit_for(self, node) -> None` — iterable check
      - `visit_return(self, node) -> None` — check return type
      - `visit_binary_op(self, node) -> LuminaType` — type inference
      - `visit_unary_op(self, node) -> LuminaType`
      - `visit_call(self, node) -> LuminaType` — check args match params
      - `visit_member_access(self, node) -> LuminaType`
      - `visit_index_access(self, node) -> LuminaType`
      - `visit_assignment(self, node) -> LuminaType` — check assignability
      - `visit_literal(self, node) -> LuminaType` — return primitive type
      - `visit_identifier(self, node) -> LuminaType` — lookup in symbol table
      - `coerce_types(self, from_type: LuminaType, to_type: LuminaType) -> bool`
      - `unify_types(self, type1: LuminaType, type2: LuminaType) -> LuminaType`
      - `report_error(self, message: str, node: ASTNode) -> None`

17. Create `lumina/typechecker/symbols.py`:
    - `Symbol` dataclass: name, type, kind, scope_level
    - `SymbolKind` enum: VARIABLE, FUNCTION, CLASS, PARAMETER, TYPE
    - `SymbolTable`:
      - `__init__(self)`
      - `enter_scope(self) -> None`
      - `exit_scope(self) -> None`
      - `define(self, name: str, type: LuminaType, kind: SymbolKind) -> None`
      - `lookup(self, name: str) -> Symbol | None`
      - `lookup_current_scope(self, name: str) -> Symbol | None`
      - `is_defined(self, name: str) -> bool`

18. Create `lumina/typechecker/errors.py`:
    - `TypeError` dataclass: message, node, expected_type, actual_type
    - `TypeMismatchError`, `UndefinedVariableError`, `WrongArgumentCountError` subclasses

=== SUBSYSTEM: IR & Bytecode ===

MODULE 7 — Intermediate Representation (`lumina/ir/`):

19. Create `lumina/ir/instructions.py`:
    - `IRInstruction` base class with opcode
    - `LoadConst`, `LoadVar`, `StoreVar` — variable operations
    - `LoadGlobal`, `StoreGlobal` — global operations
    - `LoadField`, `StoreField` — field access
    - `LoadIndex`, `StoreIndex` — array/map access
    - `BinaryOp`, `UnaryOp` — arithmetic/logic
    - `Call`, `CallMethod`, `Return` — function calls
    - `Jump`, `JumpIfTrue`, `JumpIfFalse` — control flow
    - `Label` — jump targets
    - `NewObject`, `NewArray`, `NewMap` — allocation
    - `Pop`, `Dup`, `Swap` — stack manipulation
    - `TryStart`, `TryEnd`, `Catch`, `Throw` — exception handling
    - `Print`, `PrintLn` — debug output

20. Create `lumina/ir/builder.py`:
    - `IRBuilder`:
      - `instructions: list[IRInstruction]`
      - `label_counter: int = 0`
      - `emit(self, instruction: IRInstruction) -> None`
      - `new_label(self) -> str`
      - `place_label(self, label: str) -> None`
      - `get_instructions(self) -> list[IRInstruction]`

MODULE 8 — Bytecode (`lumina/bytecode/`):

21. Create `lumina/bytecode/opcodes.py`:
    - `OpCode` enum with byte values:
      - 0x00 NOP, 0x01 CONST_INT, 0x02 CONST_FLOAT, 0x03 CONST_STRING, 0x04 CONST_BOOL, 0x05 CONST_NIL
      - 0x10 LOAD_LOCAL, 0x11 STORE_LOCAL, 0x12 LOAD_GLOBAL, 0x13 STORE_GLOBAL
      - 0x14 LOAD_FIELD, 0x15 STORE_FIELD, 0x16 LOAD_INDEX, 0x17 STORE_INDEX
      - 0x20 ADD, 0x21 SUB, 0x22 MUL, 0x23 DIV, 0x24 MOD, 0x25 POW
      - 0x30 EQ, 0x31 NE, 0x32 LT, 0x33 LE, 0x34 GT, 0x35 GE
      - 0x40 AND, 0x41 OR, 0x42 NOT, 0x43 NEG
      - 0x50 JUMP, 0x51 JUMP_IF_TRUE, 0x52 JUMP_IF_FALSE
      - 0x60 CALL, 0x61 CALL_METHOD, 0x62 RETURN, 0x63 RETURN_VALUE
      - 0x70 NEW_OBJECT, 0x71 NEW_ARRAY, 0x72 NEW_MAP, 0x73 ARRAY_APPEND
      - 0x80 POP, 0x81 DUP, 0x82 SWAP
      - 0x90 THROW, 0x91 TRY_START, 0x92 TRY_END, 0x93 CATCH
      - 0xFF HALT
    - `opcode_to_string(opcode: int) -> str`

22. Create `lumina/bytecode/chunk.py`:
    - `Chunk` class:
      - `code: bytearray` — bytecode
      - `constants: list[Any]` — constant pool
      - `lines: list[int]` — line numbers for debugging
      - `emit_byte(self, byte: int, line: int) -> None`
      - `emit_bytes(self, *bytes: int, line: int) -> None`
      - `add_constant(self, value: Any) -> int` — return index
      - `write_constant(self, value: Any, line: int) -> None`
      - `disassemble(self, name: str = "chunk") -> str` — human-readable
      - `disassemble_instruction(self, offset: int) -> tuple[str, int]` — return disassembly and new offset

23. Create `lumina/bytecode/compiler.py`:
    - `Compiler`:
      - `compile(self, program: Program) -> Chunk`
      - `current_chunk: Chunk`
      - `locals: list[Local]` — local variable tracking
      - `scope_depth: int = 0`
      - `visit_program(self, node) -> None`
      - `visit_function_decl(self, node) -> None` — compile to separate chunk
      - `visit_var_decl(self, node) -> None`
      - `visit_block(self, node) -> None`
      - `visit_if(self, node) -> None` — emit conditional jumps
      - `visit_while(self, node) -> None` — loop with back jump
      - `visit_for(self, node) -> None` — desugar to while
      - `visit_return(self, node) -> None`
      - `visit_binary_op(self, node) -> None`
      - `visit_unary_op(self, node) -> None`
      - `visit_literal(self, node) -> None` — emit constant
      - `visit_identifier(self, node) -> None` — load variable
      - `visit_assignment(self, node) -> None`
      - `visit_call(self, node) -> None`
      - `visit_member_access(self, node) -> None`
      - `visit_index_access(self, node) -> None`
      - `resolve_local(self, name: str) -> int | None` — local index or None
      - `add_local(self, name: str) -> None`
      - `begin_scope(self) -> None`, `end_scope(self) -> None`
      - `emit_byte(self, byte: int) -> None`
      - `emit_bytes(self, *bytes: int) -> None`
      - `emit_constant(self, value: Any) -> None`
      - `emit_jump(self, opcode: int) -> int` — return offset to patch
      - `patch_jump(self, offset: int) -> None`
      - `emit_loop(self, loop_start: int) -> None`

=== SUBSYSTEM: Virtual Machine ===

MODULE 9 — VM (`lumina/vm/`):

24. Create `lumina/vm/value.py`:
    - `ValueType` enum: INT, FLOAT, BOOL, NIL, STRING, OBJECT, ARRAY, FUNCTION, NATIVE
    - `Value` class:
      - `type: ValueType`, `data: Any`
      - `is_truthy(self) -> bool`
      - `as_int(self) -> int`, `as_float(self) -> float`, etc.
      - `__add__(self, other) -> Value`, `__sub__`, `__mul__`, `__truediv__`, etc.
      - `__eq__(self, other) -> bool`
      - `__repr__(self) -> str`
      - Static factories: `make_int(n)`, `make_float(f)`, `make_string(s)`, etc.

25. Create `lumina/vm/object.py`:
    - `LuminaObject` base class:
      - `class_name: str`, `fields: dict[str, Value]`
      - `get(self, name: str) -> Value`, `set(self, name: str, value: Value) -> None`
    - `LuminaArray` class: list wrapper with methods
    - `LuminaMap` class: dict wrapper
    - `LuminaFunction` class: name, chunk, arity
    - `LuminaClosure` class: function + upvalues
    - `Upvalue` class: location + closed value

26. Create `lumina/vm/vm.py`:
    - `VM` class:
      - `__init__(self)`
      - `chunk: Chunk | None`, `ip: int` — instruction pointer
      - `stack: list[Value]` — operand stack
      - `globals: dict[str, Value]`
      - `frames: list[CallFrame]` — call stack
      - `objects: list[LuminaObject]` — allocated objects for GC
      - `open_upvalues: list[Upvalue]`
      - `gray_stack: list[LuminaObject]` — for GC marking
      - `bytes_allocated: int = 0`, `next_gc: int = 1024 * 1024` — GC thresholds
      - `run(self, chunk: Chunk) -> InterpretResult` — execute chunk
      - `read_byte(self) -> int`, `read_short(self) -> int`
      - `read_constant(self) -> Value`
      - `read_string(self) -> str`
      - `push(self, value: Value) -> None`, `pop(self) -> Value`, `peek(self, distance: int = 0) -> Value`
      - `call_value(self, callee: Value, arg_count: int) -> bool` — invoke function/method
      - `call_function(self, function: LuminaFunction, arg_count: int) -> bool`
      - `call_native(self, native: Callable, arg_count: int) -> bool`
      - `define_native(self, name: str, function: Callable) -> None`
      - `capture_upvalue(self, local: int) -> Upvalue`
      - `close_upvalues(self, last: int) -> None`
      - `runtime_error(self, message: str) -> InterpretResult`
      - Main instruction dispatch loop with handler for each opcode

27. Create `lumina/vm/frame.py`:
    - `CallFrame` dataclass: function, ip, slot_offset (stack base)

28. Create `lumina/vm/result.py`:
    - `InterpretResult` enum: OK, COMPILE_ERROR, RUNTIME_ERROR
    - `VMResult` dataclass: result, value (if OK), error (if error)

=== SUBSYSTEM: Garbage Collector ===

MODULE 10 — GC (`lumina/gc/`):

29. Create `lumina/gc/collector.py`:
    - `GarbageCollector`:
      - `__init__(self, vm: VM)`
      - `collect(self) -> int` — return bytes freed
      - `mark_roots(self) -> None` — mark VM roots
      - `mark_value(self, value: Value) -> None`
      - `mark_object(self, obj: LuminaObject) -> None`
      - `trace_references(self) -> None` — trace from gray objects
      - `sweep(self) -> None` — free unmarked objects
      - `remove_white_strings(self) -> None` — interned string cleanup
      - `should_collect(self) -> bool` — check threshold

=== SUBSYSTEM: Standard Library ===

MODULE 11 — Stdlib (`lumina/stdlib/`):

30. Create `lumina/stdlib/__init__.py`:
    - `register_stdlib(vm: VM) -> None` — register all native functions

31. Create `lumina/stdlib/builtins.py`:
    - Native functions:
      - `print_native(args: list[Value]) -> Value` — print values
      - `println_native(args: list[Value]) -> Value` — print with newline
      - `input_native(args: list[Value]) -> Value` — read line from stdin
      - `int_native(args: list[Value]) -> Value` — convert to int
      - `float_native(args: list[Value]) -> Value` — convert to float
      - `string_native(args: list[Value]) -> Value` — convert to string
      - `bool_native(args: list[Value]) -> Value` — convert to bool
      - `type_native(args: list[Value]) -> Value` — get type name
      - `len_native(args: list[Value]) -> Value` — get length
      - `range_native(args: list[Value]) -> Value` — create range

32. Create `lumina/stdlib/string.py`:
    - String methods as native functions:
      - `string_length(self: str) -> int`
      - `string_concat(a: str, b: str) -> str`
      - `string_substring(s: str, start: int, end: int) -> str`
      - `string_index_of(s: str, substr: str) -> int`
      - `string_contains(s: str, substr: str) -> bool`
      - `string_starts_with(s: str, prefix: str) -> bool`
      - `string_ends_with(s: str, suffix: str) -> bool`
      - `string_split(s: str, delimiter: str) -> list`
      - `string_trim(s: str) -> str`
      - `string_to_upper(s: str) -> str`
      - `string_to_lower(s: str) -> str`
      - `string_replace(s: str, old: str, new: str) -> str`

33. Create `lumina/stdlib/array.py`:
    - Array methods:
      - `array_length(self: list) -> int`
      - `array_push(self: list, item: any) -> None`
      - `array_pop(self: list) -> any`
      - `array_shift(self: list) -> any`
      - `array_unshift(self: list, item: any) -> None`
      - `array_get(self: list, index: int) -> any`
      - `array_set(self: list, index: int, value: any) -> None`
      - `array_insert(self: list, index: int, item: any) -> None`
      - `array_remove_at(self: list, index: int) -> any`
      - `array_index_of(self: list, item: any) -> int`
      - `array_contains(self: list, item: any) -> bool`
      - `array_clear(self: list) -> None`
      - `array_slice(self: list, start: int, end: int) -> list`
      - `array_sort(self: list) -> list`
      - `array_reverse(self: list) -> list`
      - `array_map(self: list, fn: function) -> list`
      - `array_filter(self: list, fn: function) -> list`
      - `array_reduce(self: list, fn: function, initial: any) -> any`
      - `array_join(self: list, separator: str) -> str`

34. Create `lumina/stdlib/map.py`:
    - Map/dict methods:
      - `map_size(self: dict) -> int`
      - `map_get(self: dict, key: any) -> any`
      - `map_set(self: dict, key: any, value: any) -> None`
      - `map_has(self: dict, key: any) -> bool`
      - `map_delete(self: dict, key: any) -> bool`
      - `map_keys(self: dict) -> list`
      - `map_values(self: dict) -> list`
      - `map_entries(self: dict) -> list`
      - `map_clear(self: dict) -> None`

35. Create `lumina/stdlib/math.py`:
    - Math functions: abs, min, max, floor, ceil, round, sqrt, pow, sin, cos, tan, asin, acos, atan, atan2, log, log10, exp, random, seed_random

36. Create `lumina/stdlib/io.py`:
    - File I/O: read_file, write_file, append_file, file_exists, delete_file, list_directory

=== SUBSYSTEM: REPL ===

MODULE 12 — REPL (`lumina/repl/`):

37. Create `lumina/repl/repl.py`:
    - `REPL` class:
      - `__init__(self)`
      - `vm: VM`
      - `run(self) -> None` — main REPL loop
      - `read_line(self, prompt: str = ">> ") -> str`
      - `eval_line(self, line: str) -> str` — compile and execute, return result
      - `print_result(self, result: str) -> None`
      - `handle_command(self, line: str) -> bool` — :quit, :help, :clear, :vars
      - `show_help(self) -> None`
      - `clear_screen(self) -> None`
      - `list_variables(self) -> None`

=== SUBSYSTEM: Error Reporting ===

MODULE 13 — Errors (`lumina/errors/`):

38. Create `lumina/errors/reporter.py`:
    - `ErrorReporter`:
      - `errors: list`, `warnings: list`
      - `report_error(self, error) -> None`
      - `report_warning(self, warning) -> None`
      - `has_errors(self) -> bool`
      - `print_errors(self) -> None`
      - `clear(self) -> None`

39. Create `lumina/errors/printer.py`:
    - `print_error_with_context(error, source_lines) -> str` — pretty error with caret pointing

MODULE 14 — Source Maps (`lumina/sourcemap/`):

40. Create `lumina/sourcemap/mapping.py`:
    - `SourceMapping` dataclass: generated_line, generated_column, source_file, source_line, source_column, name
    - `SourceMap` class:
      - `mappings: list[SourceMapping]`
      - `add_mapping(self, gen_line, gen_col, src_file, src_line, src_col, name) -> None`
      - `lookup(self, gen_line, gen_col) -> SourceMapping | None`
      - `to_vlq(self) -> str` — encode to VLQ (simplified)

=== SUBSYSTEM: Module System ===

MODULE 15 — Modules (`lumina/modules/`):

41. Create `lumina/modules/loader.py`:
    - `ModuleLoader`:
      - `search_paths: list[str]`
      - `loaded_modules: dict[str, Module]`
      - `load(self, module_path: str) -> Module`
      - `resolve_path(self, module_path: str) -> str | None`
      - `parse_import(self, import_decl: ImportDecl) -> Module`

42. Create `lumina/modules/module.py`:
    - `Module` dataclass: name, file_path, exports (dict), chunk

=== SUBSYSTEM: Package Manager ===

MODULE 16 — Package Manager (`lumina/pm/`):

43. Create `lumina/pm/manifest.py`:
    - `PackageManifest` dataclass: name, version, description, author, dependencies, entry_point
    - `parse_manifest(path: str) -> PackageManifest`

44. Create `lumina/pm/resolver.py`:
    - `DependencyResolver`:
      - `resolve(self, manifest: PackageManifest) -> dict[str, str]` — name -> version
      - `check_conflicts(self, dependencies: dict) -> list[str]`

45. Create `lumina/pm/installer.py`:
    - `PackageInstaller` (stub):
      - `install(self, package_name: str, version: str) -> bool`
      - `download_package(self, package_name: str, version: str) -> bytes`

=== SUBSYSTEM: Formatter ===

MODULE 17 — Formatter (`lumina/formatter/`):

46. Create `lumina/formatter/formatter.py`:
    - `Formatter`:
      - `format(self, source: str) -> str` — format source code
      - `format_ast(self, ast: Program) -> str` — format from AST
      - `indent_size: int = 4`, `max_line_length: int = 100`
      - `format_statement(self, stmt, indent: int) -> str`
      - `format_expression(self, expr) -> str`

=== SUBSYSTEM: Linter ===

MODULE 18 — Linter (`lumina/linter/`):

47. Create `lumina/linter/linter.py`:
    - `Linter`:
      - `lint(self, source: str) -> list[LintIssue]`
      - `rules: list[LintRule]`
      - `check_unused_variables(self, ast) -> list[LintIssue]`
      - `check_unreachable_code(self, ast) -> list[LintIssue]`
      - `check_shadowing(self, ast) -> list[LintIssue]`

48. Create `lumina/linter/rules.py`:
    - `LintIssue` dataclass: message, line, column, severity, rule_name
    - `Severity` enum: ERROR, WARNING, INFO
    - `LintRule` base class

=== SUBSYSTEM: LSP Stub ===

MODULE 19 — LSP (`lumina/lsp/`):

49. Create `lumina/lsp/server.py`:
    - `LSPServer` (stub):
      - `initialize(self, params) -> dict` — handshake
      - `textDocument_didOpen(self, params) -> None`
      - `textDocument_didChange(self, params) -> None`
      - `textDocument_completion(self, params) -> list[dict]`
      - `textDocument_hover(self, params) -> dict | None`
      - `textDocument_definition(self, params) -> dict | None`

=== SUBSYSTEM: Test Framework ===

MODULE 20 — Test Framework (`lumina/test/`):

50. Create `lumina/test/runner.py`:
    - `TestRunner`:
      - `run_tests(self, test_files: list[str]) -> TestResults`
      - `discover_tests(self, directory: str) -> list[str]`
    - `TestResults` dataclass: passed, failed, errors, duration

51. Create `lumina/test/assertions.py`:
    - Assertion functions: assert_equals, assert_true, assert_false, assert_raises, assert_contains

=== SUBSYSTEM: Docs Generator ===

MODULE 21 — Docs (`lumina/docs/`):

52. Create `lumina/docs/generator.py`:
    - `DocsGenerator`:
      - `generate(self, source_files: list[str], output_dir: str) -> None`
      - `parse_docstring(self, text: str) -> dict`
      - `generate_markdown(self, decl: ASTNode) -> str`

=== SUBSYSTEM: Debugger ===

MODULE 22 — Debugger (`lumina/debugger/`):

53. Create `lumina/debugger/debugger.py`:
    - `Debugger`:
      - `attach(self, vm: VM) -> None`
      - `detach(self) -> None`
      - `set_breakpoint(self, file: str, line: int) -> int` — return breakpoint id
      - `remove_breakpoint(self, bp_id: int) -> bool`
      - `step_over(self) -> None`
      - `step_into(self) -> None`
      - `step_out(self) -> None`
      - `continue_execution(self) -> None`
      - `get_stack_trace(self) -> list[FrameInfo]`
      - `get_variables(self) -> dict[str, Value]`

54. Create `lumina/debugger/breakpoint.py`:
    - `Breakpoint` dataclass: id, file, line, condition, enabled, hit_count

=== SUBSYSTEM: CLI ===

MODULE 23 — CLI (`lumina/cli/`):

55. Create `lumina/cli/main.py`:
    - `main()` function with argparse
    - Subcommands:
      - `run` — execute a lumina file
      - `compile` — compile to bytecode
      - `disassemble` — disassemble bytecode
      - `repl` — start REPL
      - `fmt` — format source
      - `lint` — lint source
      - `test` — run tests
      - `doc` — generate documentation
      - `pm install` — install packages
      - `pm init` — initialize package

=== SUBSYSTEM: Tests ===

MODULE 24 — Comprehensive Test Suite (`tests/`):

56. Create `tests/lexer/`:
    - `test_lexer.py` (5 tests): test_numbers, test_strings, test_identifiers, test_operators, test_indentation
    - `test_token.py` (3 tests): test_creation, test_is_keyword, test_repr

57. Create `tests/parser/`:
    - `test_parser.py` (5 tests): test_expressions, test_statements, test_functions, test_classes, test_precedence
    - `test_precedence.py` (3 tests): test_arithmetic, test_logical, test_assignment

58. Create `tests/ast/`:
    - `test_visitor.py` (3 tests): test_visit_traversal, test_visitor_pattern

59. Create `tests/typechecker/`:
    - `test_checker.py` (4 tests): test_type_inference, test_type_errors, test_function_types, test_class_types
    - `test_symbols.py` (3 tests): test_define, test_lookup, test_scopes

60. Create `tests/bytecode/`:
    - `test_compiler.py` (4 tests): test_compile_literal, test_compile_binary, test_compile_function, test_compile_control_flow
    - `test_chunk.py` (3 tests): test_emit, test_constants, test_disassemble

61. Create `tests/vm/`:
    - `test_vm.py` (5 tests): test_arithmetic, test_variables, test_functions, test_objects, test_exceptions
    - `test_value.py` (3 tests): test_creation, test_operations, test_truthiness

62. Create `tests/stdlib/`:
    - `test_string.py` (4 tests): test_length, test_concat, test_substring, test_split
    - `test_array.py` (5 tests): test_push_pop, test_map_filter, test_reduce, test_sort, test_slice
    - `test_math.py` (3 tests): test_functions, test_random, test_trigonometry

63. Create `tests/integration/`:
    - `test_fibonacci.py` — recursive fibonacci
    - `test_factorial.py` — iterative and recursive factorial
    - `test_quicksort.py` — quicksort implementation
    - `test_linked_list.py` — linked list data structure
    - `test_binary_tree.py` — binary tree traversal

64. Create example Lumina programs in `examples/`:
    - `hello.lum` — hello world
    - `fibonacci.lum` — fibonacci sequence
    - `guess_number.lum` — number guessing game
    - `todo.lum` — simple todo list
    - `calculator.lum` — expression evaluator

Run `python -m pytest tests/ -v` to verify ALL 180+ tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No external parser generators, no LLVM, no dependencies.
- Lexer is hand-written, not using regex for tokenization.
- Parser is recursive descent, not using external parser combinators.
- VM is a stack-based bytecode interpreter (not a JIT).
- GC is mark-and-sweep, not generational.
- All native functions are pure Python (no C extensions).
- Source files use .lum extension.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=13,
        name="MEGA-3: Programming Language",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=WORKER_TIMEOUT,
        expected_test_count=180,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
