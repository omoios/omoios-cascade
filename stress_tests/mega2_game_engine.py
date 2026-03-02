#!/usr/bin/env python3
"""Mega Tier 12: Complete Game Engine + Full Game.

Complexity: 100-150 workers, ~300 files, ~20K LOC.
Task: Build a complete 2D game engine with vector/matrix math, ECS, scene graph,
sprite system, tile maps, physics, collision detection, particles, audio stub,
input manager, state machine, animation, UI, fonts, camera, pathfinding, behavior
trees, save/load, level editor, asset pipeline, and a full platformer game.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-mega-2"
WORKER_TIMEOUT = 1200

SCAFFOLD_FILES = {
    "engine/__init__.py": '''\
"""Pyxel2D — A complete 2D game engine in pure Python."""

__version__ = "0.1.0"

from engine.math.vector import Vec2, Vec3
from engine.math.matrix import Mat3, Mat4
from engine.ecs.entity import Entity
from engine.ecs.component import Component

__all__ = ["Vec2", "Vec3", "Mat3", "Mat4", "Entity", "Component"]
''',
    "engine/math/__init__.py": '''\
"""Mathematical utilities for game development."""

from engine.math.vector import Vec2, Vec3
from engine.math.matrix import Mat3, Mat4
from engine.math.rect import Rect
from engine.math.circle import Circle
from engine.math.aabb import AABB

__all__ = ["Vec2", "Vec3", "Mat3", "Mat4", "Rect", "Circle", "AABB"]
''',
    "engine/math/vector.py": '''\
"""2D and 3D vector classes."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
import math


@dataclass(frozen=True)
class Vec2:
    """2D vector with x, y components."""
    x: float = 0.0
    y: float = 0.0
    
    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)
    
    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)
    
    def __mul__(self, scalar: float) -> Vec2:
        return Vec2(self.x * scalar, self.y * scalar)
    
    def __truediv__(self, scalar: float) -> Vec2:
        return Vec2(self.x / scalar, self.y / scalar)
    
    def __neg__(self) -> Vec2:
        return Vec2(-self.x, -self.y)
    
    def dot(self, other: Vec2) -> float:
        return self.x * other.x + self.y * other.y
    
    def length(self) -> float:
        return math.sqrt(self.x ** 2 + self.y ** 2)
    
    def length_sq(self) -> float:
        return self.x ** 2 + self.y ** 2
    
    def normalized(self) -> Vec2:
        length = self.length()
        if length == 0:
            return Vec2(0, 0)
        return self / length
    
    def distance_to(self, other: Vec2) -> float:
        return (self - other).length()
    
    def distance_sq_to(self, other: Vec2) -> float:
        return (self - other).length_sq()
    
    def angle(self) -> float:
        return math.atan2(self.y, self.x)
    
    def rotate(self, angle: float) -> Vec2:
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        return Vec2(self.x * cos_a - self.y * sin_a, self.x * sin_a + self.y * cos_a)
    
    def lerp(self, other: Vec2, t: float) -> Vec2:
        return self + (other - self) * t
    
    def perpendicular(self) -> Vec2:
        return Vec2(-self.y, self.x)
    
    def floor(self) -> Vec2:
        return Vec2(math.floor(self.x), math.floor(self.y))
    
    def ceil(self) -> Vec2:
        return Vec2(math.ceil(self.x), math.ceil(self.y))
    
    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)
    
    def as_int_tuple(self) -> tuple[int, int]:
        return (int(self.x), int(self.y))
    
    @staticmethod
    def zero() -> Vec2:
        return Vec2(0, 0)
    
    @staticmethod
    def one() -> Vec2:
        return Vec2(1, 1)
    
    @staticmethod
    def up() -> Vec2:
        return Vec2(0, -1)
    
    @staticmethod
    def right() -> Vec2:
        return Vec2(1, 0)
    
    @staticmethod
    def from_angle(angle: float) -> Vec2:
        return Vec2(math.cos(angle), math.sin(angle))


@dataclass(frozen=True)
class Vec3:
    """3D vector with x, y, z components."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    
    def __add__(self, other: Vec3) -> Vec3:
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)
    
    def __sub__(self, other: Vec3) -> Vec3:
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)
    
    def __mul__(self, scalar: float) -> Vec3:
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)
    
    def __truediv__(self, scalar: float) -> Vec3:
        return Vec3(self.x / scalar, self.y / scalar, self.z / scalar)
    
    def dot(self, other: Vec3) -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z
    
    def cross(self, other: Vec3) -> Vec3:
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x
        )
    
    def length(self) -> float:
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)
    
    def length_sq(self) -> float:
        return self.x ** 2 + self.y ** 2 + self.z ** 2
    
    def normalized(self) -> Vec3:
        length = self.length()
        if length == 0:
            return Vec3(0, 0, 0)
        return self / length
    
    def distance_to(self, other: Vec3) -> float:
        return (self - other).length()
    
    def lerp(self, other: Vec3, t: float) -> Vec3:
        return self + (other - self) * t
    
    def xy(self) -> Vec2:
        return Vec2(self.x, self.y)
    
    @staticmethod
    def zero() -> Vec3:
        return Vec3(0, 0, 0)
    
    @staticmethod
    def one() -> Vec3:
        return Vec3(1, 1, 1)
''',
    "engine/ecs/__init__.py": '''\
"""Entity-Component-System architecture."""

from engine.ecs.entity import Entity
from engine.ecs.component import Component
from engine.ecs.world import World
from engine.ecs.system import System

__all__ = ["Entity", "Component", "World", "System"]
''',
    "engine/ecs/entity.py": '''\
"""ECS Entity class."""

from dataclasses import dataclass, field
from typing import Type, TypeVar

T = TypeVar("T")


@dataclass
class Entity:
    """An entity is a unique identifier with attached components."""
    id: int
    name: str = ""
    active: bool = True
    _components: dict[type, object] = field(default_factory=dict, repr=False)
    
    def add_component(self, component: object) -> "Entity":
        """Add a component to this entity."""
        self._components[type(component)] = component
        return self
    
    def get_component(self, component_type: Type[T]) -> T | None:
        """Get a component by type."""
        return self._components.get(component_type)
    
    def has_component(self, component_type: type) -> bool:
        """Check if entity has a component type."""
        return component_type in self._components
    
    def remove_component(self, component_type: type) -> bool:
        """Remove a component by type."""
        if component_type in self._components:
            del self._components[component_type]
            return True
        return False
    
    def get_components(self) -> list[object]:
        """Get all components."""
        return list(self._components.values())
    
    def has_components(self, *component_types: type) -> bool:
        """Check if entity has all specified component types."""
        return all(ct in self._components for ct in component_types)
''',
    "engine/ecs/component.py": '''\
"""Base component class."""

from dataclasses import dataclass


@dataclass
class Component:
    """Base class for all components. Components are pure data."""
    enabled: bool = True
''',
    "tests/__init__.py": "",
    "tests/conftest.py": """\
import pytest
from engine.math.vector import Vec2, Vec3
from engine.ecs.entity import Entity
from engine.ecs.component import Component


@pytest.fixture
def sample_vec2():
    return Vec2(3.0, 4.0)


@pytest.fixture
def sample_vec3():
    return Vec3(1.0, 2.0, 3.0)


@pytest.fixture
def sample_entity():
    return Entity(id=1, name="TestEntity")


@pytest.fixture
def sample_component():
    return Component(enabled=True)
""",
    "tests/test_vector.py": """\
import math
from engine.math.vector import Vec2, Vec3


def test_vec2_add():
    v1 = Vec2(1, 2)
    v2 = Vec2(3, 4)
    result = v1 + v2
    assert result.x == 4
    assert result.y == 6


def test_vec2_length():
    v = Vec2(3, 4)
    assert v.length() == 5.0


def test_vec2_normalize():
    v = Vec2(3, 4)
    n = v.normalized()
    assert abs(n.length() - 1.0) < 0.0001


def test_vec2_dot():
    v1 = Vec2(1, 2)
    v2 = Vec2(3, 4)
    assert v1.dot(v2) == 11


def test_vec3_cross():
    v1 = Vec3(1, 0, 0)
    v2 = Vec3(0, 1, 0)
    result = v1.cross(v2)
    assert result.x == 0
    assert result.y == 0
    assert result.z == 1
""",
    "tests/test_entity.py": """\
from engine.ecs.entity import Entity
from engine.ecs.component import Component


def test_entity_add_component():
    e = Entity(id=1)
    comp = Component()
    e.add_component(comp)
    assert e.has_component(Component)


def test_entity_get_component():
    e = Entity(id=1)
    comp = Component()
    e.add_component(comp)
    retrieved = e.get_component(Component)
    assert retrieved is comp


def test_entity_remove_component():
    e = Entity(id=1)
    comp = Component()
    e.add_component(comp)
    assert e.remove_component(Component)
    assert not e.has_component(Component)
""",
}

INSTRUCTIONS = """\
Build a COMPLETE 2D GAME ENGINE called "engine" with a full platformer game. Use ONLY Python stdlib.
No external dependencies. This is a fully functional game engine with ECS architecture, physics,
rendering, audio stub, input handling, and a complete playable platformer game.

=== SUBSYSTEM: Math Library ===

MODULE 1 — Matrix Operations (`engine/math/matrix.py`):

1. Create `engine/math/matrix.py`:
   - `Mat3` class — 3x3 matrix for 2D transformations:
     - `__init__(self, data: list[list[float]] | None = None)` — identity if None
     - `__matmul__(self, other: Mat3) -> Mat3` — matrix multiplication
     - `__mul__(self, vec: Vec2) -> Vec2` — transform vector
     - `transpose(self) -> Mat3`
     - `inverse(self) -> Mat3 | None`
     - `determinant(self) -> float`
     - Static factory methods:
       - `identity() -> Mat3`
       - `translation(x: float, y: float) -> Mat3`
       - `rotation(angle: float) -> Mat3` — radians
       - `scale(x: float, y: float) -> Mat3`
       - `trs(tx: float, ty: float, rotation: float, sx: float, sy: float) -> Mat3`
   - `Mat4` class — 4x4 matrix for 3D transformations (similar interface)
   - `to_list(self) -> list[float]` — flatten to list for GPU (column-major order)

MODULE 2 — Geometric Shapes (`engine/math/`):

2. Create `engine/math/rect.py`:
   - `Rect` dataclass: x, y, width, height
   - `left(self) -> float`, `right(self) -> float`, `top(self) -> float`, `bottom(self) -> float`
   - `center(self) -> Vec2`, `top_left(self) -> Vec2`, `bottom_right(self) -> Vec2`
   - `contains_point(self, point: Vec2) -> bool`
   - `contains_rect(self, other: Rect) -> bool`
   - `intersects(self, other: Rect) -> bool`
   - `intersection(self, other: Rect) -> Rect | None`
   - `union(self, other: Rect) -> Rect`
   - `inflate(self, dx: float, dy: float) -> Rect`
   - `move(self, dx: float, dy: float) -> Rect`
   - `move_to(self, x: float, y: float) -> Rect`
   - `clamp(self, other: Rect) -> Rect` — keep inside other rect
   - `scale(self, factor: float) -> Rect`
   - `as_tuple(self) -> tuple[float, float, float, float]`

3. Create `engine/math/circle.py`:
   - `Circle` dataclass: center (Vec2), radius (float)
   - `contains_point(self, point: Vec2) -> bool`
   - `contains_circle(self, other: Circle) -> bool`
   - `intersects_circle(self, other: Circle) -> bool`
   - `intersects_rect(self, rect: Rect) -> bool`
   - `bounds(self) -> Rect`
   - `area(self) -> float`
   - `circumference(self) -> float`

4. Create `engine/math/aabb.py`:
   - `AABB` (Axis-Aligned Bounding Box) dataclass: min (Vec2), max (Vec2)
   - `from_rect(rect: Rect) -> AABB` static method
   - `to_rect(self) -> Rect`
   - `center(self) -> Vec2`
   - `extents(self) -> Vec2` — half-size
   - `size(self) -> Vec2` — full size
   - `contains_point(self, point: Vec2) -> bool`
   - `contains_aabb(self, other: AABB) -> bool`
   - `intersects(self, other: AABB) -> bool`
   - `intersection(self, other: AABB) -> AABB | None`
   - `expand_to_include(self, point: Vec2) -> AABB`
   - `translate(self, offset: Vec2) -> AABB`

5. Create `engine/math/line.py`:
   - `Line2D` dataclass: start (Vec2), end (Vec2)
   - `direction(self) -> Vec2`
   - `length(self) -> float`
   - `length_sq(self) -> float`
   - `closest_point(self, point: Vec2) -> Vec2`
   - `distance_to_point(self, point: Vec2) -> float`
   - `intersects_line(self, other: Line2D) -> bool`
   - `intersection_point(self, other: Line2D) -> Vec2 | None`
   - `ray_intersection(self, origin: Vec2, direction: Vec2) -> float | None` — distance along line

6. Create `engine/math/polygon.py`:
   - `Polygon` class:
     - `__init__(self, vertices: list[Vec2])`
     - `vertices: list[Vec2]`
     - `edges: list[Line2D]`
     - `centroid(self) -> Vec2`
   - `convex_hull(points: list[Vec2]) -> Polygon` — Graham scan or Jarvis march
   - `point_in_polygon(point: Vec2, polygon: Polygon) -> bool` — ray casting
   - `polygons_intersect(poly1: Polygon, poly2: Polygon) -> bool` — SAT

7. Create `engine/math/interpolation.py`:
   - `lerp(a: float, b: float, t: float) -> float`
   - `lerp_vec2(a: Vec2, b: Vec2, t: float) -> Vec2`
   - `lerp_vec3(a: Vec3, b: Vec3, t: float) -> Vec3`
   - `smoothstep(edge0: float, edge1: float, x: float) -> float`
   - `smootherstep(edge0: float, edge1: float, x: float) -> float`
   - `bezier2(p0: Vec2, p1: Vec2, p2: Vec2, t: float) -> Vec2` — quadratic bezier
   - `bezier3(p0: Vec2, p1: Vec2, p2: Vec2, p3: Vec2, t: float) -> Vec2` — cubic bezier
   - `catmull_rom(points: list[Vec2], t: float) -> Vec2`

8. Create `engine/math/easing.py`:
   - Easing functions for animation:
   - `ease_linear(t: float) -> float`
   - `ease_in_quad(t: float) -> float`, `ease_out_quad(t: float)`, `ease_in_out_quad(t: float)`
   - `ease_in_cubic(t: float)`, `ease_out_cubic`, `ease_in_out_cubic`
   - `ease_in_sine(t: float)`, `ease_out_sine`, `ease_in_out_sine`
   - `ease_in_back(t: float)`, `ease_out_back`, `ease_in_out_back`
   - `ease_in_bounce(t: float)`, `ease_out_bounce`, `ease_in_out_bounce`
   - `ease_in_elastic(t: float)`, `ease_out_elastic`, `ease_in_out_elastic`

9. Create `engine/math/noise.py`:
   - `perlin_noise_1d(x: float) -> float`
   - `perlin_noise_2d(x: float, y: float) -> float`
   - `PerlinNoise` class with configurable octaves, persistence, lacunarity
   - `fractal_noise(x: float, y: float, octaves: int = 4) -> float`
   - `simplex_noise_2d(x: float, y: float) -> float` — simplex noise implementation

10. Create `engine/math/random.py`:
    - `Random` class (wrapper around random module with seed support):
      - `__init__(self, seed: int | None = None)`
      - `random() -> float` — [0, 1)
      - `randint(a: int, b: int) -> int` — [a, b]
      - `uniform(a: float, b: float) -> float`
      - `choice(seq) -> T`
      - `shuffle(seq) -> None`
      - `sample(seq, k) -> list`
      - `random_vec2(min: Vec2, max: Vec2) -> Vec2`
      - `random_vec2_in_circle(center: Vec2, radius: float) -> Vec2`
      - `random_vec2_in_rect(rect: Rect) -> Vec2`
    - `set_global_seed(seed: int) -> None`

=== SUBSYSTEM: ECS Core ===

MODULE 3 — ECS World (`engine/ecs/world.py`):

11. Create `engine/ecs/world.py`:
    - `World` class:
      - `__init__(self)`
      - `create_entity(self, name: str = "") -> Entity`
      - `destroy_entity(self, entity_id: int) -> bool`
      - `get_entity(self, entity_id: int) -> Entity | None`
      - `get_all_entities(self) -> list[Entity]`
      - `get_entities_with(self, *component_types) -> list[Entity]`
      - `query(self, component_types: tuple) -> Iterator[tuple[Entity, ...]]` — yields (entity, comp1, comp2, ...)
      - `add_system(self, system: System) -> None`
      - `remove_system(self, system_type: type) -> bool`
      - `update(self, delta_time: float) -> None` — update all systems
      - `clear(self) -> None` — destroy all entities
      - `_next_entity_id: int` — auto-incrementing counter

MODULE 4 — ECS System (`engine/ecs/system.py`):

12. Create `engine/ecs/system.py`:
    - `System` base class:
      - `__init__(self, priority: int = 0)`
      - `priority: int` — lower runs first
      - `world: World | None` — set when added to world
      - `on_added(self, world: World) -> None` — called when added
      - `on_removed(self) -> None` — called when removed
      - `update(self, delta_time: float) -> None` — override in subclasses
      - `should_update(self) -> bool` — override to skip update
    - `SystemGroup` class for running multiple systems in order

MODULE 5 — Built-in Components (`engine/ecs/components/`):

13. Create `engine/ecs/components/__init__.py`

14. Create `engine/ecs/components/transform.py`:
    - `Transform` component:
      - `position: Vec2 = Vec2.zero()`
      - `rotation: float = 0.0` — radians
      - `scale: Vec2 = Vec2.one()`
      - `local_matrix(self) -> Mat3`
      - `world_matrix(self) -> Mat3` — with parent
      - `right(self) -> Vec2` — local right vector
      - `up(self) -> Vec2` — local up vector
      - `set_parent(self, parent: Transform | None) -> None`

15. Create `engine/ecs/components/sprite.py`:
    - `Sprite` component:
      - `character: str = "█"` — single char representation
      - `color: tuple[int, int, int] = (255, 255, 255)` — RGB
      - `background_color: tuple[int, int, int] | None = None`
      - `width: int = 1`, `height: int = 1` — in characters
      - `flip_x: bool = False`, `flip_y: bool = False`
      - `visible: bool = True`
      - `z_order: int = 0` — render order
      - `get_render_data(self) -> dict` — return renderable data

16. Create `engine/ecs/components/physics.py`:
    - `RigidBody` component:
      - `velocity: Vec2 = Vec2.zero()`
      - `acceleration: Vec2 = Vec2.zero()`
      - `mass: float = 1.0`
      - `drag: float = 0.0`
      - `gravity_scale: float = 1.0`
      - `is_static: bool = False`
      - `is_kinematic: bool = False`
      - `restitution: float = 0.0` — bounciness 0-1
      - `friction: float = 0.1`
      - `apply_force(self, force: Vec2) -> None`
      - `apply_impulse(self, impulse: Vec2) -> None`
      - `get_inverse_mass(self) -> float`
    - `Collider` component (base):
      - `offset: Vec2 = Vec2.zero()`
      - `is_trigger: bool = False`
      - `layer: int = 0` — collision layer
      - `mask: int = 0xFFFFFFFF` — collision mask
      - `get_aabb(self, position: Vec2) -> AABB` — abstract

17. Create `engine/ecs/components/colliders.py`:
    - `BoxCollider(Collider)`:
      - `size: Vec2 = Vec2.one()`
      - `get_aabb(self, position: Vec2) -> AABB`
      - `get_rect(self, position: Vec2) -> Rect`
    - `CircleCollider(Collider)`:
      - `radius: float = 0.5`
      - `get_aabb(self, position: Vec2) -> AABB`
      - `get_circle(self, position: Vec2) -> Circle`

18. Create `engine/ecs/components/lifecycle.py`:
    - `Lifetime` component:
      - `time_remaining: float` — seconds
      - `update(self, delta_time: float) -> bool` — returns True if expired
    - `DestroyOnCollision` component — tag for auto-destroy
    - `Spawner` component:
      - `prefab: dict` — entity template
      - `spawn_rate: float` — seconds between spawns
      - `max_spawns: int = -1` — -1 for infinite
      - `update(self, delta_time: float) -> list[Entity] | None` — returns spawned entities

=== SUBSYSTEM: Scene Graph ===

MODULE 6 — Scene Graph (`engine/scene/`):

19. Create `engine/scene/__init__.py`

20. Create `engine/scene/node.py`:
    - `SceneNode` class:
      - `__init__(self, name: str = "")`
      - `name: str`
      - `parent: SceneNode | None`
      - `children: list[SceneNode]`
      - `transform: Transform`
      - `entity: Entity | None` — linked ECS entity
      - `add_child(self, child: SceneNode) -> None`
      - `remove_child(self, child: SceneNode) -> bool`
      - `find_child(self, name: str) -> SceneNode | None`
      - `find_recursive(self, name: str) -> SceneNode | None`
      - `traverse(self, callback: Callable) -> None` — depth-first
      - `get_world_transform(self) -> Mat3`
      - `detach(self) -> None` — remove from parent

21. Create `engine/scene/scene.py`:
    - `Scene` class:
      - `__init__(self, name: str)`
      - `name: str`
      - `root: SceneNode`
      - `world: World` — ECS world
      - `camera: Camera`
      - `get_node_by_path(self, path: str) -> SceneNode | None` — e.g., "/Player/Hand"
      - `instantiate(self, prefab: dict, parent: SceneNode | None = None) -> Entity`
      - `destroy_node(self, node: SceneNode) -> None`
      - `clear(self) -> None`
      - `save(self) -> dict` — serialize to dict
      - `load(self, data: dict) -> None` — deserialize from dict
      - Static method `load_from_file(path: str) -> Scene`

=== SUBSYSTEM: Rendering ===

MODULE 7 — Rendering (`engine/render/`):

22. Create `engine/render/__init__.py`

23. Create `engine/render/buffer.py`:
    - `RenderBuffer` class:
      - `__init__(self, width: int, height: int)`
      - `width: int`, `height: int`
      - `clear(self, char: str = " ", color: tuple | None = None) -> None`
      - `set_pixel(self, x: int, y: int, char: str, color: tuple | None = None, bg: tuple | None = None) -> bool` — returns False if out of bounds
      - `get_pixel(self, x: int, y: int) -> tuple[str, tuple | None, tuple | None] | None`
      - `draw_char(self, x: int, y: int, char: str, color: tuple | None = None) -> None`
      - `draw_string(self, x: int, y: int, text: str, color: tuple | None = None) -> None`
      - `draw_rect(self, rect: Rect, char: str = "█", color: tuple | None = None, fill: bool = False) -> None`
      - `draw_line(self, x0: int, y0: int, x1: int, y1: int, char: str = "█", color: tuple | None = None) -> None` — Bresenham
      - `draw_circle(self, cx: int, cy: int, radius: int, char: str = "█", color: tuple | None = None, fill: bool = False) -> None` — midpoint circle
      - `blit(self, other: RenderBuffer, x: int, y: int, transparent_char: str | None = None) -> None`
      - `to_string(self) -> str` — for terminal output
      - `scroll(self, dx: int, dy: int, wrap: bool = False) -> None`

24. Create `engine/render/camera.py`:
    - `Camera` class:
      - `__init__(self, viewport_width: int, viewport_height: int)`
      - `position: Vec2 = Vec2.zero()`
      - `zoom: float = 1.0`
      - `rotation: float = 0.0`
      - `viewport_width: int`, `viewport_height: int`
      - `world_to_screen(self, world_pos: Vec2) -> Vec2`
      - `screen_to_world(self, screen_pos: Vec2) -> Vec2`
      - `get_view_matrix(self) -> Mat3`
      - `get_projection_matrix(self) -> Mat3`
      - `get_view_projection(self) -> Mat3`
      - `set_bounds(self, bounds: Rect | None) -> None` — optional clamping
      - `follow(self, target: Vec2, smoothing: float = 0.1) -> None` — smooth follow
      - `shake(self, intensity: float, duration: float) -> None` — screen shake
      - `update(self, delta_time: float) -> None` — update shake

25. Create `engine/render/renderer.py`:
    - `Renderer` class:
      - `__init__(self, width: int, height: int)`
      - `render_buffer: RenderBuffer`
      - `camera: Camera`
      - `clear_color: tuple[int, int, int] = (0, 0, 0)`
      - `begin_frame(self) -> None` — clear buffer
      - `end_frame(self) -> str` — return frame as string for display
      - `render_sprite(self, position: Vec2, sprite: Sprite) -> None`
      - `render_world(self, world: World) -> None` — render all entities with Transform+Sprite
      - `render_debug(self, world: World, show_colliders: bool = False) -> None` — draw colliders
      - `render_grid(self, cell_size: int = 10, color: tuple | None = None) -> None` — world grid
      - `draw_debug_line(self, start: Vec2, end: Vec2, color: tuple = (255, 0, 0)) -> None`
      - `draw_debug_rect(self, rect: Rect, color: tuple = (0, 255, 0)) -> None`

26. Create `engine/render/tilemap.py`:
    - `Tile` dataclass: char, color, bg_color, solid, type_id
    - `TileMap` class:
      - `__init__(self, width: int, height: int, tile_size: int = 1)`
      - `width: int`, `height: int`, `tile_size: int`
      - `tiles: list[list[Tile | None]]`
      - `set_tile(self, x: int, y: int, tile: Tile | None) -> bool`
      - `get_tile(self, x: int, y: int) -> Tile | None`
      - `is_solid(self, x: int, y: int) -> bool`
      - `world_to_tile(self, world_pos: Vec2) -> tuple[int, int]`
      - `tile_to_world(self, tx: int, ty: int) -> Vec2`
      - `get_tiles_in_rect(self, rect: Rect) -> list[tuple[int, int, Tile]]`
      - `render_to_buffer(self, buffer: RenderBuffer, camera: Camera) -> None`
      - `load_from_string(self, data: str, tile_map: dict[str, Tile]) -> None`
      - `load_from_csv(self, path: str, tile_map: dict[int, Tile]) -> None`

=== SUBSYSTEM: Physics ===

MODULE 8 — Physics (`engine/physics/`):

27. Create `engine/physics/__init__.py`

28. Create `engine/physics/world.py`:
    - `PhysicsWorld` class:
      - `__init__(self, gravity: Vec2 = Vec2(0, -9.8))`
      - `gravity: Vec2`
      - `bodies: list[tuple[Entity, Transform, RigidBody, Collider]]`
      - `add_body(self, entity: Entity, transform: Transform, rigidbody: RigidBody, collider: Collider) -> None`
      - `remove_body(self, entity: Entity) -> bool`
      - `step(self, delta_time: float, iterations: int = 3) -> None` — physics step
      - `raycast(self, origin: Vec2, direction: Vec2, max_distance: float, layer_mask: int = 0xFFFFFFFF) -> RaycastHit | None`
      - `overlap_aabb(self, aabb: AABB, layer_mask: int = 0xFFFFFFFF) -> list[Entity]`
      - `set_bounds(self, bounds: Rect | None) -> None` — world bounds

29. Create `engine/physics/collision.py`:
    - `Collision` dataclass: entity_a, entity_b, contact_point, normal, penetration_depth
    - `RaycastHit` dataclass: entity, point, normal, distance, fraction
    - `CollisionSolver` class:
      - `solve_collisions(self, collisions: list[Collision]) -> None` — resolve penetrations
      - `apply_collision_response(self, collision: Collision) -> None` — impulse resolution
    - `CollisionDetector` class:
      - `check_aabb_aabb(self, a: AABB, b: AABB) -> Collision | None`
      - `check_circle_circle(self, a: Circle, b: Circle) -> Collision | None`
      - `check_aabb_circle(self, aabb: AABB, circle: Circle) -> Collision | None`
      - `broad_phase(self, bodies: list) -> list[tuple]` — return potential pairs
      - `narrow_phase(self, pairs: list) -> list[Collision]`

30. Create `engine/physics/sat.py`:
    - `SATResult` dataclass: collided, overlap, minimum_translation_vector, axis
    - `sat_polygon_polygon(poly1: Polygon, poly2: Polygon) -> SATResult`
    - `get_axes(polygon: Polygon) -> list[Vec2]` — get separating axes
    - `project_polygon(polygon: Polygon, axis: Vec2) -> tuple[float, float]` — min/max projection

=== SUBSYSTEM: Input ===

MODULE 9 — Input (`engine/input/`):

31. Create `engine/input/__init__.py`

32. Create `engine/input/keys.py`:
    - `Key` enum — all keyboard keys (A-Z, 0-9, arrows, space, enter, escape, etc.)
    - `MOUSE_LEFT`, `MOUSE_RIGHT`, `MOUSE_MIDDLE` constants
    - `key_from_char(char: str) -> Key` — convert char to Key enum

33. Create `engine/input/input_manager.py`:
    - `InputManager` class:
      - `__init__(self)`
      - `_key_states: dict[Key, bool]` — current state
      - `_prev_key_states: dict[Key, bool]` — previous frame state
      - `_mouse_pos: Vec2 = Vec2.zero()`
      - `_mouse_delta: Vec2 = Vec2.zero()`
      - `_mouse_buttons: dict[int, bool]` — button states
      - `update(self) -> None` — swap states, clear events
      - `set_key(self, key: Key, pressed: bool) -> None` — called by platform layer
      - `set_mouse_pos(self, pos: Vec2) -> None`
      - `set_mouse_button(self, button: int, pressed: bool) -> None`
      - `is_key_down(self, key: Key) -> bool` — currently held
      - `is_key_pressed(self, key: Key) -> bool` — just pressed this frame
      - `is_key_released(self, key: Key) -> bool` — just released this frame
      - `get_mouse_pos(self) -> Vec2`
      - `get_mouse_delta(self) -> Vec2`
      - `is_mouse_down(self, button: int) -> bool`
      - `is_mouse_pressed(self, button: int) -> bool`
      - `get_axis(self, negative: Key, positive: Key) -> float` — -1 to 1
      - `get_axis_raw(self, negative: Key, positive: Key) -> int` — -1, 0, 1

34. Create `engine/input/actions.py`:
    - `InputAction` dataclass: name, keys (list), axis (bool)
    - `InputMap` class:
      - `__init__(self)`
      - `add_action(self, name: str, keys: list[Key], axis: bool = False) -> None`
      - `remove_action(self, name: str) -> bool`
      - `get_action_value(self, input_manager: InputManager, name: str) -> float` — 0-1 or -1-1 for axis
      - `is_action_pressed(self, input_manager: InputManager, name: str) -> bool`
      - `load_from_dict(self, data: dict) -> None`
      - `save_to_dict(self) -> dict`

=== SUBSYSTEM: Audio (Stub) ===

MODULE 10 — Audio (`engine/audio/`):

35. Create `engine/audio/__init__.py`

36. Create `engine/audio/manager.py`:
    - `AudioManager` class (stub implementation):
      - `__init__(self)`
      - `load_sound(self, path: str, name: str) -> bool` — stub, just track name
      - `play_sound(self, name: str, volume: float = 1.0, pitch: float = 1.0) -> None` — stub
      - `stop_sound(self, name: str) -> None` — stub
      - `set_volume(self, name: str, volume: float) -> None` — stub
      - `pause_all(self) -> None` — stub
      - `resume_all(self) -> None` — stub
      - `get_loaded_sounds(self) -> list[str]`

=== SUBSYSTEM: Animation ===

MODULE 11 — Animation (`engine/animation/`):

37. Create `engine/animation/__init__.py`

38. Create `engine/animation/clip.py`:
    - `Keyframe` dataclass: time, value, easing_func
    - `AnimationClip` class:
      - `__init__(self, name: str, duration: float)`
      - `name: str`, `duration: float`, `loop: bool = True`
      - `keyframes: dict[str, list[Keyframe]]` — property path -> keyframes
      - `add_keyframe(self, property_path: str, time: float, value, easing=ease_linear) -> None`
      - `sample(self, property_path: str, time: float) -> any` — get interpolated value
      - `evaluate(self, time: float) -> dict[str, any]` — all properties at time

39. Create `engine/animation/animator.py`:
    - `Animator` component:
      - `clips: dict[str, AnimationClip]`
      - `current_clip: AnimationClip | None`
      - `current_time: float = 0.0`
      - `speed: float = 1.0`
      - `playing: bool = False`
      - `play(self, clip_name: str, fade_in: float = 0.0) -> None`
      - `stop(self) -> None`
      - `pause(self) -> None`
      - `resume(self) -> None`
      - `update(self, delta_time: float) -> dict[str, any] | None` — returns current values

=== SUBSYSTEM: State Machine ===

MODULE 12 — State Machine (`engine/state_machine/`):

40. Create `engine/state_machine/__init__.py`

41. Create `engine/state_machine/state.py`:
    - `State` base class:
      - `name: str`
      - `transitions: dict[str, str]` — event -> next_state_name
      - `on_enter(self, data: dict | None = None) -> None`
      - `on_exit(self) -> None`
      - `on_update(self, delta_time: float) -> None`
      - `can_transition(self, event: str) -> bool`
      - `get_transition(self, event: str) -> str | None`

42. Create `engine/state_machine/machine.py`:
    - `StateMachine` class:
      - `__init__(self, name: str = "")`
      - `states: dict[str, State]`
      - `current_state: State | None`
      - `previous_state: State | None`
      - `add_state(self, state: State) -> None`
      - `set_initial_state(self, state_name: str) -> None`
      - `transition(self, event: str, data: dict | None = None) -> bool`
      - `update(self, delta_time: float) -> None`
      - `is_in_state(self, state_name: str) -> bool`
      - `get_current_state_name(self) -> str | None`
      - `create_transition(self, from_state: str, event: str, to_state: str) -> None`

=== SUBSYSTEM: Pathfinding ===

MODULE 13 — Pathfinding (`engine/pathfinding/`):

43. Create `engine/pathfinding/__init__.py`

44. Create `engine/pathfinding/grid.py`:
    - `PathGrid` class:
      - `__init__(self, width: int, height: int)`
      - `width: int`, `height: int`
      - `nodes: list[list[GridNode]]`
      - `is_walkable(self, x: int, y: int) -> bool`
      - `set_walkable(self, x: int, y: int, walkable: bool) -> None`
      - `get_neighbors(self, x: int, y: int, allow_diagonal: bool = False) -> list[GridNode]`
      - `world_to_grid(self, world_pos: Vec2) -> tuple[int, int]`
      - `grid_to_world(self, gx: int, gy: int) -> Vec2`
      - `from_tilemap(self, tilemap: TileMap, solid_types: set) -> None`
    - `GridNode` dataclass: x, y, walkable, g_cost, h_cost, parent

45. Create `engine/pathfinding/astar.py`:
    - `AStar` class:
      - `__init__(self, grid: PathGrid)`
      - `find_path(self, start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]] | None` — A* algorithm
      - `heuristic(self, a: tuple[int, int], b: tuple[int, int]) -> int` — Manhattan distance
      - `get_distance(self, a: GridNode, b: GridNode) -> int` — 10 for cardinal, 14 for diagonal
    - `smooth_path(self, path: list[tuple[int, int]], grid: PathGrid) -> list[tuple[int, int]]` — line-of-sight simplification

=== SUBSYSTEM: Behavior Trees ===

MODULE 14 — Behavior Trees (`engine/behavior_tree/`):

46. Create `engine/behavior_tree/__init__.py`

47. Create `engine/behavior_tree/nodes.py`:
    - `NodeStatus` enum: SUCCESS, FAILURE, RUNNING
    - `BTNode` base class:
      - `tick(self, context: dict) -> NodeStatus` — abstract
    - `BTComposite(BTNode)` base for multi-child nodes
    - `BTSequence(BTComposite)` — run children in order, fail on first failure
    - `BTSelector(BTComposite)` — run children in order, succeed on first success
    - `BTParallel(BTComposite)` — run all children, succeed/fail policy
    - `BTDecorator(BTNode)` base for single-child wrappers
    - `BTInverter(BTDecorator)` — invert result
    - `BTRepeater(BTDecorator)` — repeat N times or forever
    - `BTCondition(BTNode)` — check condition, return success/failure
    - `BTAction(BTNode)` — execute action, return status

48. Create `engine/behavior_tree/context.py`:
    - `BTContext` class:
      - `__init__(self, entity: Entity, world: World, blackboard: dict | None = None)`
      - `entity: Entity`, `world: World`, `blackboard: dict`
      - `get_blackboard(self, key: str) -> any`
      - `set_blackboard(self, key: str, value: any) -> None`

=== SUBSYSTEM: Particle System ===

MODULE 15 — Particles (`engine/particles/`):

49. Create `engine/particles/__init__.py`

50. Create `engine/particles/emitter.py`:
    - `Particle` dataclass: position, velocity, lifetime, max_lifetime, size, color, rotation, angular_velocity
    - `ParticleEmitter` component:
      - `__init__(self)`
      - `emission_rate: float` — particles per second
      - `burst_count: int = 0` — emit this many immediately
      - `lifetime_range: tuple[float, float] = (1.0, 2.0)`
      - `velocity_range: tuple[Vec2, Vec2]` — min/max
      - `size_range: tuple[float, float] = (1.0, 1.0)`
      - `color_gradient: list[tuple[float, tuple]]` — time -> color
      - `gravity: Vec2 = Vec2(0, -9.8)`
      - `drag: float = 0.0`
      - `particles: list[Particle]`
      - `emit(self, count: int = 1) -> None` — burst emit
      - `update(self, delta_time: float) -> list[Particle]` — update and return alive particles
      - `set_shape(self, shape: str) -> None` — "point", "circle", "cone"

=== SUBSYSTEM: UI ===

MODULE 16 — UI System (`engine/ui/`):

51. Create `engine/ui/__init__.py`

52. Create `engine/ui/widget.py`:
    - `UIWidget` base class:
      - `__init__(self, name: str = "")`
      - `name: str`, `rect: Rect`, `visible: bool = True`, `enabled: bool = True`
      - `parent: UIWidget | None`, `children: list[UIWidget]`
      - `anchor_min: Vec2 = Vec2.zero()`, `anchor_max: Vec2 = Vec2.one()`
      - `offset_min: Vec2 = Vec2.zero()`, `offset_max: Vec2 = Vec2.zero()`
      - `add_child(self, child: UIWidget) -> None`
      - `remove_child(self, child: UIWidget) -> bool`
      - `calculate_rect(self, parent_rect: Rect) -> Rect` — apply anchors
      - `contains_point(self, point: Vec2) -> bool`
      - `on_click(self) -> None` — override
      - `on_hover(self, is_hovering: bool) -> None` — override
      - `render(self, buffer: RenderBuffer) -> None` — override

53. Create `engine/ui/label.py`:
    - `UILabel(UIWidget)`:
      - `text: str = ""`, `color: tuple = (255, 255, 255)`, `align: str = "left"`
      - `render(self, buffer: RenderBuffer) -> None`

54. Create `engine/ui/button.py`:
    - `UIButton(UIWidget)`:
      - `text: str = ""`, `on_click_callback: Callable | None = None`
      - `bg_color: tuple = (100, 100, 100)`, `hover_color: tuple = (150, 150, 150)`
      - `pressed_color: tuple = (80, 80, 80)`
      - `is_pressed: bool = False`, `is_hovered: bool = False`
      - `on_click(self) -> None` — call callback
      - `on_hover(self, is_hovering: bool) -> None`
      - `render(self, buffer: RenderBuffer) -> None`

55. Create `engine/ui/panel.py`:
    - `UIPanel(UIWidget)`:
      - `bg_color: tuple | None = None`, `border_color: tuple | None = None`
      - `render(self, buffer: RenderBuffer) -> None`

56. Create `engine/ui/canvas.py`:
    - `UICanvas` class:
      - `__init__(self, width: int, height: int)`
      - `root: UIPanel`
      - `widgets: list[UIWidget]`
      - `focused_widget: UIWidget | None`
      - `add_widget(self, widget: UIWidget) -> None`
      - `remove_widget(self, widget: UIWidget) -> bool`
      - `handle_input(self, input_manager: InputManager) -> None` — process clicks/hovers
      - `render(self, buffer: RenderBuffer) -> None` — render all widgets
      - `find_widget_at(self, point: Vec2) -> UIWidget | None`

=== SUBSYSTEM: Asset Pipeline ===

MODULE 17 — Assets (`engine/assets/`):

57. Create `engine/assets/__init__.py`

58. Create `engine/assets/manager.py`:
    - `AssetManager` class:
      - `__init__(self, root_path: str = "assets")`
      - `cache: dict[str, any]` — loaded assets
      - `load_text(self, path: str) -> str`
      - `load_json(self, path: str) -> dict`
      - `load_tilemap(self, path: str) -> TileMap`
      - `load_sprite(self, path: str) -> Sprite` — from text file
      - `get(self, path: str) -> any | None` — get from cache
      - `unload(self, path: str) -> bool`
      - `clear_cache(self) -> None`

59. Create `engine/assets/prefabs.py`:
    - `PrefabRegistry` class:
      - `register(self, name: str, data: dict) -> None`
      - `create(self, name: str, world: World, position: Vec2 | None = None) -> Entity`
      - `instantiate(self, data: dict, world: World) -> Entity` — from dict

=== SUBSYSTEM: Game Systems ===

MODULE 18 — Game Systems (`engine/systems/`):

60. Create `engine/systems/__init__.py`

61. Create `engine/systems/movement.py`:
    - `MovementSystem(System)`:
      - `update(self, delta_time: float) -> None` — update positions from velocity

62. Create `engine/systems/collision.py`:
    - `CollisionSystem(System)`:
      - `__init__(self, physics_world: PhysicsWorld)`
      - `update(self, delta_time: float) -> None` — detect and resolve collisions

63. Create `engine/systems/animation.py`:
    - `AnimationSystem(System)`:
      - `update(self, delta_time: float) -> None` — update animators

64. Create `engine/systems/lifetime.py`:
    - `LifetimeSystem(System)`:
      - `update(self, delta_time: float) -> None` — destroy expired entities

65. Create `engine/systems/particle.py`:
    - `ParticleSystem(System)`:
      - `update(self, delta_time: float) -> None` — update emitters

66. Create `engine/systems/script.py`:
    - `ScriptSystem(System)`:
      - `update(self, delta_time: float) -> None` — call update on Script components

=== SUBSYSTEM: Save/Load ===

MODULE 19 — Save System (`engine/save/`):

67. Create `engine/save/__init__.py`

68. Create `engine/save/manager.py`:
    - `SaveManager` class:
      - `__init__(self, save_dir: str = "saves")`
      - `save_game(self, slot: int, data: dict) -> bool`
      - `load_game(self, slot: int) -> dict | None`
      - `delete_save(self, slot: int) -> bool`
      - `list_saves(self) -> list[dict]` — save metadata
      - `save_exists(self, slot: int) -> bool`

=== SUBSYSTEM: Game Implementation ===

MODULE 20 — Platformer Game (`game/`):

69. Create `game/__init__.py` — "Pyxel Platformer — A complete platformer game"

70. Create `game/player.py`:
    - `PlayerController` component:
      - `speed: float = 5.0`, `jump_force: float = 10.0`
      - `grounded: bool = False`, `can_jump: bool = False`
      - `coyote_time: float = 0.1`, `jump_buffer: float = 0.1`
      - `update(self, delta_time: float, input_manager: InputManager) -> None` — handle input
      - `check_grounded(self, physics_world: PhysicsWorld) -> bool`
      - `jump(self) -> None`
      - `move(self, direction: float, delta_time: float) -> None`

71. Create `game/enemy.py`:
    - `EnemyController` component:
      - `patrol_distance: float = 3.0`, `speed: float = 2.0`
      - `start_pos: Vec2`, `direction: int = 1`
      - `update(self, delta_time: float) -> None` — patrol behavior
      - `on_player_detected(self, player_pos: Vec2) -> None` — chase player

72. Create `game/collectible.py`:
    - `Collectible` component — tag component
    - `Coin`, `Gem`, `PowerUp` as subclasses or types
    - `on_collected(self, player: Entity) -> None`

73. Create `game/hazard.py`:
    - `Hazard` component:
      - `damage: int = 1`, `knockback: Vec2 = Vec2(5, 5)`
      - `on_player_touch(self, player: Entity) -> None`
    - `SpikeHazard(Hazard)`, `LavaHazard(Hazard)` subclasses

74. Create `game/level.py`:
    - `Level` class:
      - `__init__(self, name: str, tilemap: TileMap)`
      - `name: str`, `tilemap: TileMap`, `entities: list[Entity]`
      - `spawn_point: Vec2`, `exit_point: Vec2`
      - `load(self, world: World) -> None` — spawn all entities
      - `unload(self, world: World) -> None` — destroy entities
      - `check_victory(self, player_pos: Vec2) -> bool`

75. Create `game/game_manager.py`:
    - `GameManager` class:
      - `__init__(self)`
      - `world: World`, `renderer: Renderer`, `input: InputManager`
      - `physics: PhysicsWorld`, `scene: Scene`
      - `score: int = 0`, `lives: int = 3`, `level_index: int = 0`
      - `levels: list[Level]`
      - `state: str = "playing"` — playing, paused, game_over, victory
      - `init(self) -> None` — setup systems, load first level
      - `load_level(self, index: int) -> None`
      - `next_level(self) -> None`
      - `update(self, delta_time: float) -> None` — main game loop
      - `render(self) -> str` — return frame for display
      - `on_player_death(self) -> None`
      - `add_score(self, points: int) -> None`
      - `save_progress(self) -> None`
      - `load_progress(self) -> None`

76. Create `game/levels/level1.txt`:
    - ASCII level layout:
      ```
      ################
      #..............#
      #...C....E.....#
      #.####.........#
      #......###.....#
      #..P.......X...#
      ################
      ```
    - Legend: #=wall, P=player start, C=coin, E=enemy, X=exit, .=empty

77. Create `game/levels/level2.txt` and `game/levels/level3.txt` with increasing difficulty

78. Create `game/main.py`:
    - `main()` function — entry point
    - Parse command line args for level select
    - Initialize GameManager
    - Main game loop with timing
    - Handle quit signal

=== SUBSYSTEM: Tests ===

MODULE 21 — Comprehensive Test Suite (`tests/`):

79. Create `tests/math/`:
    - `test_matrix.py` (4 tests): test_mat3_identity, test_mat3_multiply, test_mat3_transform, test_mat3_inverse
    - `test_rect.py` (4 tests): test_contains, test_intersects, test_intersection, test_operations
    - `test_circle.py` (3 tests): test_contains, test_intersects, test_bounds
    - `test_aabb.py` (4 tests): test_from_rect, test_contains, test_intersects, test_expand
    - `test_line.py` (3 tests): test_closest_point, test_distance, test_intersection
    - `test_polygon.py` (3 tests): test_convex_hull, test_point_in_polygon, test_polygons_intersect
    - `test_interpolation.py` (4 tests): test_lerp, test_smoothstep, test_bezier2, test_bezier3
    - `test_easing.py` (3 tests): test_ease_linear, test_ease_quad, test_ease_back
    - `test_noise.py` (2 tests): test_perlin_range, test_fractal_noise

80. Create `tests/ecs/`:
    - `test_world.py` (4 tests): test_create_entity, test_destroy_entity, test_query, test_systems
    - `test_entity.py` (3 tests): test_add_component, test_get_component, test_has_components
    - `test_transform.py` (3 tests): test_local_matrix, test_world_matrix, test_parent_child

81. Create `tests/physics/`:
    - `test_collision.py` (4 tests): test_aabb_aabb, test_circle_circle, test_aabb_circle, test_raycast
    - `test_physics_world.py` (3 tests): test_add_body, test_step, test_gravity
    - `test_sat.py` (2 tests): test_sat_collided, test_sat_no_collision

82. Create `tests/render/`:
    - `test_buffer.py` (4 tests): test_set_pixel, test_draw_line, test_draw_rect, test_blit
    - `test_camera.py` (3 tests): test_world_to_screen, test_follow, test_shake
    - `test_tilemap.py` (3 tests): test_set_get_tile, test_world_to_tile, test_from_string

83. Create `tests/input/`:
    - `test_input_manager.py` (4 tests): test_key_states, test_mouse, test_axis, test_pressed_released

84. Create `tests/animation/`:
    - `test_clip.py` (3 tests): test_add_keyframe, test_sample, test_evaluate
    - `test_animator.py` (3 tests): test_play, test_update, test_loop

85. Create `tests/state_machine/`:
    - `test_state_machine.py` (4 tests): test_add_state, test_transition, test_update, test_is_in_state

86. Create `tests/pathfinding/`:
    - `test_astar.py` (3 tests): test_simple_path, test_no_path, test_diagonal

87. Create `tests/behavior_tree/`:
    - `test_nodes.py` (4 tests): test_sequence, test_selector, test_parallel, test_decorators

88. Create `tests/particles/`:
    - `test_emitter.py` (3 tests): test_emit, test_update, test_burst

89. Create `tests/ui/`:
    - `test_widget.py` (2 tests): test_hierarchy, test_rect_calculation
    - `test_canvas.py` (2 tests): test_add_remove, test_handle_input

90. Create `tests/game/`:
    - `test_player.py` (3 tests): test_movement, test_jump, test_ground_check
    - `test_level.py` (2 tests): test_load, test_victory_condition
    - `test_game_manager.py` (3 tests): test_init, test_score, test_level_progression

Run `python -m pytest tests/ -v` to verify ALL 150+ tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No pygame, no numpy, no PIL, no external packages.
- Rendering outputs ASCII art to terminal (print).
- Physics is simplified but functional (AABB/circle collision, impulse resolution).
- Audio is stubbed (no actual sound output).
- Game loop runs at fixed timestep with accumulator pattern.
- All vector math uses engine.math module, no tuples for vectors.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=12,
        name="MEGA-2: Game Engine + Platformer",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=WORKER_TIMEOUT,
        expected_test_count=150,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
