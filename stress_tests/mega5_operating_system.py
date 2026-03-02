#!/usr/bin/env python3
"""Mega Tier 15: Operating System Simulation.

Complexity: 150-200 workers, ~400 files, ~25K LOC.
Task: Build a complete OS simulation with process scheduler (round-robin, priority),
memory manager (paging, virtual memory), file system (inode-based), device drivers
(stub), system calls, shell (parsing, pipes, redirection, job control), core utilities
(ls, cat, grep, find, sort, wc, head, tail, cp, mv, rm, mkdir, chmod, echo, env,
export, alias, history), text editor (vi-like), package manager, init system,
logging daemon, network stack (stub), user management, permissions, signals, IPC.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-mega-5"
WORKER_TIMEOUT = 1800

SCAFFOLD_FILES = {
    "os/__init__.py": '''\
"""NanoOS — A complete operating system simulation in pure Python."""

__version__ = "0.1.0"
__kernel_version__ = "1.0.0"

from os.kernel.process import Process
from os.kernel.scheduler import Scheduler
from os.fs.filesystem import FileSystem

__all__ = ["Process", "Scheduler", "FileSystem"]
''',
    "os/kernel/__init__.py": '''\
"""Kernel subsystem — process management, memory, and scheduling."""

from os.kernel.process import Process, ProcessState
from os.kernel.scheduler import Scheduler
from os.kernel.memory import MemoryManager

__all__ = ["Process", "ProcessState", "Scheduler", "MemoryManager"]
''',
    "os/kernel/process.py": '''\
"""Process model for the OS simulation."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


class ProcessState(Enum):
    NEW = auto()
    READY = auto()
    RUNNING = auto()
    WAITING = auto()
    TERMINATED = auto()
    ZOMBIE = auto()


class ProcessPriority(Enum):
    IDLE = 0
    LOW = 1
    NORMAL = 2
    HIGH = 3
    REALTIME = 4


@dataclass
class Process:
    """A process in the operating system."""
    pid: int
    ppid: int  # parent process ID
    name: str
    state: ProcessState = ProcessState.NEW
    priority: ProcessPriority = ProcessPriority.NORMAL
    
    # Memory
    code_size: int = 0  # bytes
    data_size: int = 0  # bytes
    stack_size: int = 0  # bytes
    heap_size: int = 0  # bytes
    page_table: dict[int, int] = field(default_factory=dict)  # virtual -> physical
    
    # CPU
    program_counter: int = 0
    registers: dict[str, int] = field(default_factory=dict)
    
    # Scheduling
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    cpu_time: float = 0.0  # seconds
    wait_time: float = 0.0  # seconds
    last_scheduled: datetime | None = None
    time_slice_remaining: float = 0.0  # quantum remaining
    
    # I/O
    open_files: list[int] = field(default_factory=list)  # file descriptors
    current_directory: str = "/"
    
    # Signals
    pending_signals: list[int] = field(default_factory=list)
    signal_handlers: dict[int, Any] = field(default_factory=dict)
    
    # Exit status
    exit_code: int | None = None
    terminated_at: datetime | None = None
    
    metadata: dict = field(default_factory=dict)
    
    def is_running(self) -> bool:
        return self.state == ProcessState.RUNNING
    
    def is_terminated(self) -> bool:
        return self.state == ProcessState.TERMINATED
    
    def total_memory(self) -> int:
        return self.code_size + self.data_size + self.stack_size + self.heap_size
''',
    "os/kernel/scheduler.py": '''\
"""Process scheduler implementations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable
import heapq

from os.kernel.process import Process, ProcessState, ProcessPriority


@dataclass
class SchedulingStats:
    """Statistics for scheduler performance."""
    context_switches: int = 0
    total_wait_time: float = 0.0
    total_turnaround_time: float = 0.0
    processes_completed: int = 0


class Scheduler(ABC):
    """Abstract base class for process schedulers."""
    
    def __init__(self, time_quantum: float = 0.1):
        self.time_quantum = time_quantum  # seconds
        self.ready_queue: list[Process] = []
        self.blocked_queue: list[Process] = []
        self.current_process: Process | None = None
        self.stats = SchedulingStats()
    
    @abstractmethod
    def add_process(self, process: Process) -> None:
        """Add a process to the ready queue."""
        pass
    
    @abstractmethod
    def schedule(self) -> Process | None:
        """Select the next process to run."""
        pass
    
    def block_process(self, process: Process) -> None:
        """Block a process (waiting for I/O)."""
        process.state = ProcessState.WAITING
        if process in self.ready_queue:
            self.ready_queue.remove(process)
        self.blocked_queue.append(process)
    
    def unblock_process(self, process: Process) -> None:
        """Unblock a process (I/O completed)."""
        if process in self.blocked_queue:
            self.blocked_queue.remove(process)
            process.state = ProcessState.READY
            self.add_process(process)
    
    def terminate_process(self, process: Process, exit_code: int = 0) -> None:
        """Mark a process as terminated."""
        process.state = ProcessState.TERMINATED
        process.exit_code = exit_code
        if process in self.ready_queue:
            self.ready_queue.remove(process)
        if process == self.current_process:
            self.current_process = None
        self.stats.processes_completed += 1
    
    def tick(self, delta_time: float) -> Process | None:
        """Update scheduler state, return process to switch to (if any)."""
        if self.current_process:
            self.current_process.time_slice_remaining -= delta_time
            self.current_process.cpu_time += delta_time
            
            if self.current_process.time_slice_remaining <= 0:
                # Time slice expired
                self.current_process.state = ProcessState.READY
                self.add_process(self.current_process)
                self.current_process = None
                return self.schedule()
        
        return None
    
    def get_stats(self) -> SchedulingStats:
        return self.stats
''',
    "os/fs/__init__.py": '''\
"""File system subsystem."""

from os.fs.filesystem import FileSystem
from os.fs.inode import INode, FileType
from os.fs.block import Block

__all__ = ["FileSystem", "INode", "FileType", "Block"]
''',
    "os/fs/inode.py": '''\
"""INode (index node) for file system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional


class FileType(Enum):
    REGULAR = auto()
    DIRECTORY = auto()
    SYMLINK = auto()
    DEVICE = auto()
    PIPE = auto()
    SOCKET = auto()


class Permission(Enum):
    READ = 0o4
    WRITE = 0o2
    EXECUTE = 0o1


@dataclass
class INode:
    """File system index node."""
    inode_number: int
    file_type: FileType = FileType.REGULAR
    
    # Permissions (Unix-style: owner/group/other)
    mode: int = 0o644  # rw-r--r--
    uid: int = 0  # owner user ID
    gid: int = 0  # owner group ID
    
    # Metadata
    size: int = 0  # bytes
    block_count: int = 0
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    accessed_at: datetime = field(default_factory=datetime.now)
    
    # Data blocks (direct, indirect, double-indirect)
    direct_blocks: list[int] = field(default_factory=lambda: [0] * 12)
    indirect_block: int = 0
    double_indirect_block: int = 0
    
    # Links
    link_count: int = 1
    symlink_target: str = ""  # if FileType.SYMLINK
    
    # Reference to file system
    fs: Optional["FileSystem"] = None  # type: ignore
    
    def is_directory(self) -> bool:
        return self.file_type == FileType.DIRECTORY
    
    def is_regular_file(self) -> bool:
        return self.file_type == FileType.REGULAR
    
    def is_symlink(self) -> bool:
        return self.file_type == FileType.SYMLINK
    
    def check_permission(self, user_id: int, group_ids: list[int], permission: Permission) -> bool:
        """Check if user has specified permission."""
        if user_id == 0:  # root
            return True
        
        if user_id == self.uid:
            return (self.mode >> 6) & permission.value == permission.value
        
        if self.gid in group_ids:
            return (self.mode >> 3) & permission.value == permission.value
        
        return self.mode & permission.value == permission.value
    
    def can_read(self, user_id: int, group_ids: list[int]) -> bool:
        return self.check_permission(user_id, group_ids, Permission.READ)
    
    def can_write(self, user_id: int, group_ids: list[int]) -> bool:
        return self.check_permission(user_id, group_ids, Permission.WRITE)
    
    def can_execute(self, user_id: int, group_ids: list[int]) -> bool:
        return self.check_permission(user_id, group_ids, Permission.EXECUTE)
    
    def set_mode(self, mode: int) -> None:
        self.mode = mode & 0o7777
        self.modified_at = datetime.now()
    
    def mode_string(self) -> str:
        """Return mode as ls-style string (e.g., '-rw-r--r--')."""
        type_char = {
            FileType.REGULAR: '-',
            FileType.DIRECTORY: 'd',
            FileType.SYMLINK: 'l',
            FileType.DEVICE: 'c',
            FileType.PIPE: 'p',
            FileType.SOCKET: 's',
        }[self.file_type]
        
        def mode_triplet(bits: int) -> str:
            return (
                ('r' if bits & 0o4 else '-') +
                ('w' if bits & 0o2 else '-') +
                ('x' if bits & 0o1 else '-')
            )
        
        return (
            type_char +
            mode_triplet(self.mode >> 6) +
            mode_triplet((self.mode >> 3) & 0o7) +
            mode_triplet(self.mode & 0o7)
        )
''',
    "tests/__init__.py": "",
    "tests/conftest.py": """\
import pytest
from os.kernel.process import Process, ProcessState, ProcessPriority
from os.kernel.scheduler import RoundRobinScheduler
from os.fs.inode import INode, FileType


@pytest.fixture
def sample_process():
    return Process(
        pid=1,
        ppid=0,
        name="init",
        state=ProcessState.READY,
        priority=ProcessPriority.NORMAL
    )


@pytest.fixture
def sample_inode():
    return INode(
        inode_number=1,
        file_type=FileType.REGULAR,
        mode=0o644,
        uid=1000,
        gid=1000,
        size=1024
    )


@pytest.fixture
def sample_scheduler():
    return RoundRobinScheduler(time_quantum=0.1)
""",
    "tests/test_process.py": """\
from os.kernel.process import Process, ProcessState, ProcessPriority


def test_process_creation():
    p = Process(pid=1, ppid=0, name="init")
    assert p.state == ProcessState.NEW
    assert p.priority == ProcessPriority.NORMAL


def test_process_is_running():
    p = Process(pid=1, ppid=0, name="test")
    assert not p.is_running()
    p.state = ProcessState.RUNNING
    assert p.is_running()


def test_process_total_memory():
    p = Process(pid=1, ppid=0, name="test", code_size=100, data_size=200)
    assert p.total_memory() == 300
""",
    "tests/test_inode.py": """\
from os.fs.inode import INode, FileType, Permission


def test_inode_mode_string():
    inode = INode(inode_number=1, file_type=FileType.REGULAR, mode=0o644)
    assert inode.mode_string() == "-rw-r--r--"


def test_inode_is_directory():
    inode = INode(inode_number=1, file_type=FileType.DIRECTORY)
    assert inode.is_directory()
    assert not inode.is_regular_file()


def test_inode_check_permission():
    inode = INode(inode_number=1, mode=0o644, uid=1000, gid=1000)
    assert inode.can_read(1000, [1000])
    assert inode.can_write(1000, [1000])
    assert not inode.can_execute(1000, [1000])
""",
}

INSTRUCTIONS = """\
Build a COMPLETE OPERATING SYSTEM SIMULATION called "os". Use ONLY Python stdlib.
No external dependencies. This is a comprehensive OS simulation with process scheduling,
memory management (paging), file system (inode-based), shell, core utilities, and more.

=== SUBSYSTEM: Kernel — Process Management ===

MODULE 1 — Process Table (`os/kernel/process_table.py`):

1. Create `os/kernel/process_table.py`:
   - `ProcessTable` class:
     - `__init__(self, max_processes: int = 1024)`
     - `processes: dict[int, Process]` — pid -> Process
     - `next_pid: int = 1`
     - `allocate_pid(self) -> int`
     - `add(self, process: Process) -> bool`
     - `get(self, pid: int) -> Process | None`
     - `remove(self, pid: int) -> bool`
     - `list_all(self) -> list[Process]`
     - `find_by_name(self, name: str) -> list[Process]`
     - `find_children(self, ppid: int) -> list[Process]`
     - `get_next_runnable(self) -> Process | None`
     - `get_stats(self) -> dict` — total, running, waiting, zombie counts

MODULE 2 — Scheduler Implementations (`os/kernel/schedulers/`):

2. Create `os/kernel/schedulers/__init__.py` — export all schedulers

3. Create `os/kernel/schedulers/fifo.py`:
   - `FIFOScheduler(Scheduler)` — First Come First Served:
     - `add_process(self, process: Process) -> None` — append to queue
     - `schedule(self) -> Process | None` — return first in queue

4. Create `os/kernel/schedulers/round_robin.py`:
   - `RoundRobinScheduler(Scheduler)`:
     - `add_process(self, process: Process) -> None` — append to queue
     - `schedule(self) -> Process | None` — pop from front, set time slice
     - Time quantum management per priority level

5. Create `os/kernel/schedulers/priority.py`:
   - `PriorityScheduler(Scheduler)`:
     - `add_process(self, process: Process) -> None` — insert by priority
     - `schedule(self) -> Process | None` — highest priority first
     - `aging_factor: float = 0.1` — boost priority of waiting processes
     - `apply_aging(self) -> None` — increase priority of waiting processes

6. Create `os/kernel/schedulers/multilevel_queue.py`:
   - `MultilevelQueueScheduler(Scheduler)`:
     - Multiple queues by priority: realtime, high, normal, low, idle
     - `queues: dict[ProcessPriority, deque[Process]]`
     - Scheduling between queues (higher priority queues first)
     - Time quantum per queue (shorter for high priority)

7. Create `os/kernel/schedulers/multilevel_feedback.py`:
   - `MultilevelFeedbackQueueScheduler(Scheduler)`:
     - Multiple queues with priority boost
     - Demote processes that use full time slice
     - Promote processes that block frequently
     - Priority boost after certain time in lower queues

MODULE 3 — System Calls (`os/kernel/syscalls.py`):

8. Create `os/kernel/syscalls.py`:
   - `Syscall` enum: FORK, EXEC, EXIT, WAIT, KILL, GETPID, GETPPID, SLEEP
   - `SyscallHandler` class:
     - `handle_fork(self, process: Process) -> int` — create child process
     - `handle_exec(self, process: Process, path: str, args: list[str]) -> int`
     - `handle_exit(self, process: Process, code: int) -> None`
     - `handle_wait(self, process: Process, pid: int) -> tuple[int, int]` — (child_pid, exit_code)
     - `handle_kill(self, process: Process, pid: int, signal: int) -> bool`
     - `handle_getpid(self, process: Process) -> int`
     - `handle_sleep(self, process: Process, seconds: float) -> None`

MODULE 4 — Signals (`os/kernel/signals.py`):

9. Create `os/kernel/signals.py`:
   - `Signal` enum: SIGHUP(1), SIGINT(2), SIGQUIT(3), SIGILL(4), SIGABRT(6), SIGFPE(8), SIGKILL(9), SIGSEGV(11), SIGPIPE(13), SIGALRM(14), SIGTERM(15), SIGCHLD(17), SIGCONT(18), SIGSTOP(19), SIGTSTP(20)
   - `SignalAction` enum: DEFAULT, IGNORE, HANDLE
   - `SignalManager`:
     - `default_actions: dict[Signal, SignalAction]`
     - `send_signal(self, target_pid: int, signal: Signal) -> bool`
     - `deliver_signal(self, process: Process, signal: Signal) -> None`
     - `set_handler(self, process: Process, signal: Signal, handler: Callable | None) -> None`
     - `check_pending(self, process: Process) -> Signal | None`
     - `SIG_DFL`, `SIG_IGN` constants

=== SUBSYSTEM: Kernel — Memory Management ===

MODULE 5 — Memory Management (`os/kernel/memory.py`):

10. Create `os/kernel/memory.py`:
    - `MemoryManager`:
      - `__init__(self, total_memory: int, page_size: int = 4096)`
      - `total_memory: int`, `page_size: int`, `total_pages: int`
      - `page_table: dict[int, PageFrame]` — page number -> frame
      - `free_frames: list[int]` — list of available frame numbers
      - `used_frames: set[int]`
      - `allocate_pages(self, num_pages: int) -> list[int]` — return frame numbers
      - `free_pages(self, frames: list[int]) -> None`
      - `translate_address(self, virtual_addr: int, page_table: dict) -> int` — virtual to physical
      - `allocate_for_process(self, process: Process, code_size: int, data_size: int, stack_size: int) -> bool`
      - `free_process_memory(self, process: Process) -> None`
      - `get_stats(self) -> dict` — total, used, free

11. Create `os/kernel/paging.py`:
    - `PageTableEntry` dataclass: frame_number, present, writable, user_mode, accessed, dirty
    - `PageTable`:
      - `entries: dict[int, PageTableEntry]` — virtual page -> entry
      - `add_mapping(self, virtual_page: int, physical_frame: int, flags: dict) -> None`
      - `remove_mapping(self, virtual_page: int) -> None`
      - `lookup(self, virtual_page: int) -> PageTableEntry | None`
      - `is_present(self, virtual_page: int) -> bool`

12. Create `os/kernel/virtual_memory.py`:
    - `VirtualMemoryManager`:
      - `__init__(self, memory_manager: MemoryManager)`
      - `page_tables: dict[int, PageTable]` — pid -> page table
      - `swap_space: dict[int, bytes]` — page number -> swapped data
      - `handle_page_fault(self, pid: int, virtual_addr: int) -> bool` — load from swap or allocate
      - `swap_out_page(self, pid: int, virtual_page: int) -> bool`
      - `swap_in_page(self, pid: int, virtual_page: int) -> bool`
      - `find_victim_page(self) -> tuple[int, int]` — (pid, virtual_page) using LRU

=== SUBSYSTEM: File System ===

MODULE 6 — File System Core (`os/fs/`):

13. Create `os/fs/superblock.py`:
    - `Superblock` dataclass:
      - `magic: int = 0x4E414E4F`  # "NANO"
      - `block_size: int = 4096`
      - `total_blocks: int`
      - `total_inodes: int`
      - `free_blocks: int`
      - `free_inodes: int`
      - `inode_table_start: int`
      - `data_blocks_start: int`
      - `mounted_at: datetime`
      - `last_check: datetime`

14. Create `os/fs/block.py`:
    - `Block` class:
      - `__init__(self, number: int, size: int = 4096)`
      - `number: int`, `data: bytearray`, `dirty: bool = False`
      - `read(self, offset: int, size: int) -> bytes`
      - `write(self, offset: int, data: bytes) -> int` — bytes written
      - `clear(self) -> None`

15. Create `os/fs/bitmap.py`:
    - `Bitmap`:
      - `__init__(self, size: int)`
      - `data: bytearray`
      - `set(self, index: int) -> None`
      - `clear(self, index: int) -> None`
      - `is_set(self, index: int) -> bool`
      - `find_first_zero(self) -> int | None` — find free slot
      - `find_first_set(self) -> int | None`

16. Create `os/fs/directory.py`:
    - `DirectoryEntry` dataclass: name (str), inode_number (int), entry_type (FileType)
    - `Directory`:
      - `__init__(self, inode: INode)`
      - `entries: dict[str, DirectoryEntry]`
      - `add_entry(self, name: str, inode_number: int, entry_type: FileType) -> bool`
      - `remove_entry(self, name: str) -> bool`
      - `get_entry(self, name: str) -> DirectoryEntry | None`
      - `list_entries(self) -> list[DirectoryEntry]`
      - `is_empty(self) -> bool`
      - `serialize(self) -> bytes`
      - `deserialize(self, data: bytes) -> None`

17. Create `os/fs/filesystem.py`:
    - `FileSystem`:
      - `__init__(self, device_path: str, num_blocks: int = 1024, block_size: int = 4096)`
      - `superblock: Superblock`
      - `inode_bitmap: Bitmap`, `block_bitmap: Bitmap`
      - `inode_table: dict[int, INode]`
      - `blocks: dict[int, Block]`
      - `open_files: dict[int, tuple[int, int, str]]` — fd -> (inode, position, mode)
      - `next_fd: int = 0`
      - `format(self) -> None` — create new file system
      - `mount(self) -> None` — load existing file system
      - `allocate_inode(self, file_type: FileType) -> INode | None`
      - `free_inode(self, inode_number: int) -> bool`
      - `allocate_block(self) -> int | None` — return block number
      - `free_block(self, block_number: int) -> bool`
      - `create_file(self, path: str, mode: int = 0o644) -> INode | None`
      - `create_directory(self, path: str, mode: int = 0o755) -> INode | None`
      - `create_symlink(self, path: str, target: str) -> INode | None`
      - `lookup(self, path: str) -> INode | None` — resolve path to inode
      - `open_file(self, path: str, mode: str = "r") -> int | None` — return fd
      - `close_file(self, fd: int) -> bool`
      - `read(self, fd: int, size: int) -> bytes`
      - `write(self, fd: int, data: bytes) -> int` — bytes written
      - `seek(self, fd: int, position: int, whence: int = 0) -> int` — return new position
      - `unlink(self, path: str) -> bool`
      - `rmdir(self, path: str) -> bool`
      - `rename(self, old_path: str, new_path: str) -> bool`
      - `chmod(self, path: str, mode: int) -> bool`
      - `chown(self, path: str, uid: int, gid: int) -> bool`
      - `stat(self, path: str) -> dict | None`
      - `read_inode_data(self, inode: INode) -> bytes`
      - `write_inode_data(self, inode: INode, data: bytes) -> bool`
      - `_resolve_path(self, path: str, cwd: str = "/") -> list[str]` — normalize path
      - `_get_or_create_indirect_block(self, inode: INode, index: int) -> int`

MODULE 7 — File Descriptor Table (`os/fs/fd_table.py`):

18. Create `os/fs/fd_table.py`:
    - `FileDescriptorTable`:
      - `__init__(self)`
      - `entries: dict[int, FDEntry]` — fd -> entry
      - `allocate(self, inode: int, flags: int) -> int` — return fd
      - `free(self, fd: int) -> bool`
      - `get(self, fd: int) -> FDEntry | None`
      - `duplicate(self, fd: int) -> int` — dup
      - `duplicate_to(self, old_fd: int, new_fd: int) -> bool` — dup2
    - `FDEntry` dataclass: inode_number, position: int, flags: int, refcount: int

=== SUBSYSTEM: Device Drivers ===

MODULE 8 — Device Drivers (`os/drivers/`):

19. Create `os/drivers/__init__.py`

20. Create `os/drivers/device.py`:
    - `Device` base class:
      - `name: str`, `major: int`, `minor: int`
      - `open(self) -> int | None` — return fd
      - `close(self, fd: int) -> bool`
      - `read(self, fd: int, size: int) -> bytes`
      - `write(self, fd: int, data: bytes) -> int`
      - `ioctl(self, fd: int, request: int, arg: any) -> int`

21. Create `os/drivers/tty.py`:
    - `TTYDevice(Device)` — terminal:
      - `read_line(self) -> str`
      - `write_string(self, s: str) -> None`
      - `set_echo(self, enabled: bool) -> None`
      - `set_raw(self, enabled: bool) -> None`

22. Create `os/drivers/null.py`:
    - `NullDevice(Device)` — /dev/null:
      - `read` returns empty bytes
      - `write` discards data

23. Create `os/drivers/zero.py`:
    - `ZeroDevice(Device)` — /dev/zero:
      - `read` returns zeros
      - `write` discards

24. Create `os/drivers/random.py`:
    - `RandomDevice(Device)` — /dev/random:
      - `read` returns random bytes
      - Uses random module

25. Create `os/drivers/device_manager.py`:
    - `DeviceManager`:
      - `devices: dict[tuple[int, int], Device]` — (major, minor) -> Device
      - `register(self, device: Device) -> None`
      - `unregister(self, major: int, minor: int) -> bool`
      - `lookup(self, major: int, minor: int) -> Device | None`
      - `create_device_file(self, path: str, device: Device, fs: FileSystem) -> bool`

=== SUBSYSTEM: Shell ===

MODULE 9 — Shell Core (`os/shell/`):

26. Create `os/shell/__init__.py`

27. Create `os/shell/lexer.py`:
    - `ShellToken` dataclass: type, value, position
    - `ShellTokenType` enum: WORD, STRING, PIPE, REDIRECT_IN, REDIRECT_OUT, REDIRECT_APPEND, REDIRECT_ERR, SEMICOLON, AMPERSAND, NEWLINE, EOF
    - `ShellLexer`:
      - `tokenize(self, input: str) -> list[ShellToken]`
      - Handle quoting (single/double), escaping, variable expansion

28. Create `os/shell/parser.py`:
    - `Command` dataclass: argv (list[str]), redirects (list), background (bool)
    - `Pipeline` dataclass: commands (list[Command])
    - `Job` dataclass: pipeline (Pipeline), job_id (int), status
    - `ShellParser`:
      - `parse(self, tokens: list[ShellToken]) -> Pipeline`
      - Handle pipelines, redirections, background processes

29. Create `os/shell/expansion.py`:
    - `expand_variables(self, token: str, env: dict) -> str` — $VAR, ${VAR}
    - `expand_tilde(self, token: str, home: str) -> str` — ~, ~user
    - `expand_glob(self, pattern: str, fs: FileSystem, cwd: str) -> list[str]` — *, ?
    - `quote_removal(self, token: str) -> str`

30. Create `os/shell/job_control.py`:
    - `JobControl`:
      - `jobs: dict[int, Job]`
      - `next_job_id: int = 1`
      - `add_job(self, pipeline: Pipeline, pgid: int) -> int` — return job_id
      - `remove_job(self, job_id: int) -> bool`
      - `get_job(self, job_id: int) -> Job | None`
      - `list_jobs(self) -> list[Job]`
      - `foreground_job(self, job_id: int) -> bool`
      - `background_job(self, job_id: int) -> bool`
      - `wait_for_job(self, job_id: int) -> int` — return exit status

31. Create `os/shell/redirection.py`:
    - `RedirectionHandler`:
      - `apply_redirects(self, redirects: list, fs: FileSystem) -> dict[int, int]` — return fd mapping
      - `redirect_input(self, path: str) -> int` — return new fd
      - `redirect_output(self, path: str, append: bool = False) -> int`
      - `redirect_error(self, path: str) -> int`
      - `restore_fds(self, original: dict[int, int]) -> None`

32. Create `os/shell/shell.py`:
    - `Shell`:
      - `__init__(self, fs: FileSystem, scheduler: Scheduler)`
      - `env: dict[str, str]` — environment variables
      - `aliases: dict[str, str]`
      - `history: list[str]`
      - `history_file: str = ".history"`
      - `running: bool = True`
      - `last_exit_code: int = 0`
      - `run(self) -> None` — main REPL
      - `run_interactive(self) -> None`
      - `run_script(self, path: str) -> int`
      - `execute_line(self, line: str) -> int` — exit code
      - `execute_pipeline(self, pipeline: Pipeline) -> int`
      - `execute_command(self, command: Command) -> int`
      - `builtin_cd(self, args: list[str]) -> int`
      - `builtin_exit(self, args: list[str]) -> int`
      - `builtin_export(self, args: list[str]) -> int`
      - `builtin_alias(self, args: list[str]) -> int`
      - `builtin_unalias(self, args: list[str]) -> int`
      - `builtin_history(self, args: list[str]) -> int`
      - `builtin_jobs(self, args: list[str]) -> int`
      - `builtin_fg(self, args: list[str]) -> int`
      - `builtin_bg(self, args: list[str]) -> int`
      - `builtin_source(self, args: list[str]) -> int`
      - `resolve_command(self, name: str) -> str | None` — search PATH
      - `load_history(self) -> None`
      - `save_history(self) -> None`
      - `add_to_history(self, line: str) -> None`

=== SUBSYSTEM: Core Utilities ===

MODULE 10 — Core Utilities (`os/bin/`):

33. Create `os/bin/__init__.py`

34. Create `os/bin/ls.py`:
    - `ls_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -l (long), -a (all), -h (human readable), -r (reverse), -t (sort by time)
    - Output format matching real ls

35. Create `os/bin/cat.py`:
    - `cat_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -n (number lines), -b (number non-blank), -s (squeeze blank)
    - Handle multiple files, stdin (-)

36. Create `os/bin/grep.py`:
    - `grep_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -i (ignore case), -v (invert), -n (line numbers), -r (recursive), -l (files only)
    - Pattern matching: literal and simple regex (., *, ^, $)

37. Create `os/bin/find.py`:
    - `find_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -name, -type, -size, -mtime
    - Actions: -print, -exec

38. Create `os/bin/sort.py`:
    - `sort_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -r (reverse), -n (numeric), -k (key), -t (delimiter), -u (unique)

39. Create `os/bin/wc.py`:
    - `wc_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -l (lines), -w (words), -c (bytes), -m (chars)
    - Default: all three

40. Create `os/bin/head.py`:
    - `head_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -n (lines), -c (bytes)
    - Default: first 10 lines

41. Create `os/bin/tail.py`:
    - `tail_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -n (lines), -c (bytes), -f (follow)
    - Default: last 10 lines

42. Create `os/bin/cp.py`:
    - `cp_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -r (recursive), -v (verbose), -i (interactive)

43. Create `os/bin/mv.py`:
    - `mv_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -v (verbose), -i (interactive), -f (force)

44. Create `os/bin/rm.py`:
    - `rm_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -r (recursive), -f (force), -v (verbose), -i (interactive)

45. Create `os/bin/mkdir.py`:
    - `mkdir_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -p (parents), -v (verbose), -m (mode)

46. Create `os/bin/rmdir.py`:
    - `rmdir_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -p (parents), -v (verbose)

47. Create `os/bin/chmod.py`:
    - `chmod_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Support symbolic (u+x) and numeric (755) modes
    - Options: -R (recursive), -v (verbose)

48. Create `os/bin/chown.py`:
    - `chown_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Format: chown [user][:group] file...
    - Options: -R (recursive), -v (verbose)

49. Create `os/bin/echo.py`:
    - `echo_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -n (no newline), -e (enable escapes)

50. Create `os/bin/env.py`:
    - `env_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Print environment or run command with modified env

51. Create `os/bin/pwd.py`:
    - `pwd_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -L (logical), -P (physical)

52. Create `os/bin/ln.py`:
    - `ln_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -s (symbolic), -f (force), -v (verbose)

53. Create `os/bin/touch.py`:
    - `touch_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Create empty file or update timestamps
    - Options: -a (access time), -m (mod time), -t (specify time)

54. Create `os/bin/whoami.py`:
    - `whoami_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Print current user name

55. Create `os/bin/uname.py`:
    - `uname_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Options: -a (all), -s (kernel), -n (hostname), -r (release), -v (version), -m (machine)

56. Create `os/bin/date.py`:
    - `date_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Print or set system date
    - Format: +FORMAT

57. Create `os/bin/test.py`:
    - `test_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - File tests: -e, -f, -d, -r, -w, -x, -s
    - String tests: -z, -n, =, !=
    - Numeric tests: -eq, -ne, -lt, -le, -gt, -ge

58. Create `os/bin/which.py`:
    - `which_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Locate a command in PATH

=== SUBSYSTEM: Text Editor ===

MODULE 11 — Text Editor (`os/bin/vi/`):

59. Create `os/bin/vi/__init__.py`

60. Create `os/bin/vi/buffer.py`:
    - `TextBuffer`:
      - `lines: list[str]`
      - `filename: str | None`
      - `modified: bool = False`
      - `cursor_line: int = 0`, `cursor_col: int = 0`
      - `insert(self, text: str) -> None`
      - `delete_char(self) -> str`
      - `delete_line(self, line: int) -> str`
      - `get_line(self, line: int) -> str`
      - `set_line(self, line: int, text: str) -> None`
      - `load(self, fs: FileSystem, path: str) -> bool`
      - `save(self, fs: FileSystem, path: str | None = None) -> bool`

61. Create `os/bin/vi/editor.py`:
    - `VIEditor`:
      - `__init__(self, fs: FileSystem)`
      - `buffer: TextBuffer`
      - `mode: str = "normal"` — normal, insert, command, visual
      - `running: bool = True`
      - `command_buffer: str = ""`
      - `search_pattern: str = ""`
      - `clipboard: str = ""`
      - `undo_stack: list`, `redo_stack: list`
      - `run(self, filename: str | None = None) -> None`
      - `process_input(self, key: str) -> None`
      - `normal_mode_command(self, key: str) -> None` — h, j, k, l, i, a, o, x, dd, yy, p, u, Ctrl-r, :, /, n, N
      - `insert_mode_command(self, key: str) -> None`
      - `command_mode_command(self, cmd: str) -> None` — :w, :q, :wq, :q!, :x, :set, :/
      - `render(self) -> str` — return screen content
      - `move_cursor(self, direction: str, count: int = 1) -> None`
      - `search(self, pattern: str, forward: bool = True) -> bool`

=== SUBSYSTEM: User Management ===

MODULE 12 — User Management (`os/users/`):

62. Create `os/users/__init__.py`

63. Create `os/users/user.py`:
    - `User` dataclass: uid, username, gid, home, shell, password_hash, gecos

64. Create `os/users/group.py`:
    - `Group` dataclass: gid, name, members (list of usernames)

65. Create `os/users/passwd.py`:
    - `PasswdFile`:
      - `users: dict[int, User]`, `users_by_name: dict[str, User]`
      - `load(self, fs: FileSystem, path: str = "/etc/passwd") -> None`
      - `save(self, fs: FileSystem, path: str = "/etc/passwd") -> None`
      - `get_by_uid(self, uid: int) -> User | None`
      - `get_by_name(self, name: str) -> User | None`
      - `add_user(self, user: User) -> None`
      - `remove_user(self, uid: int) -> bool`

66. Create `os/users/group_file.py`:
    - `GroupFile`:
      - Similar to PasswdFile for /etc/group

67. Create `os/users/shadow.py`:
    - `ShadowFile` — password hashes for /etc/shadow

68. Create `os/users/auth.py`:
    - `Authenticator`:
      - `authenticate(self, username: str, password: str) -> User | None`
      - `check_password(self, user: User, password: str) -> bool`

=== SUBSYSTEM: Init System ===

MODULE 13 — Init System (`os/init/`):

69. Create `os/init/__init__.py`

70. Create `os/init/init.py`:
    - `Init`:
      - `__init__(self, fs: FileSystem, scheduler: Scheduler)`
      - `runlevel: int = 3`
      - `services: dict[str, Service]`
      - `boot(self) -> None` — system initialization
      - `read_inittab(self, path: str = "/etc/inittab") -> list[InitEntry]`
      - `start_service(self, name: str) -> bool`
      - `stop_service(self, name: str) -> bool`
      - `change_runlevel(self, runlevel: int) -> None`
      - `reap_zombies(self) -> None`
      - `handle_signal(self, signal: int) -> None`
    - `InitEntry` dataclass: id, runlevels, action, process
    - `Service` dataclass: name, command, pid: int | None, status

71. Create `os/init/runlevels.py`:
    - `RunlevelManager`:
      - `runlevels: dict[int, list[str]]` — runlevel -> services
      - `get_services_for_runlevel(self, runlevel: int) -> list[str]`
      - `is_service_in_runlevel(self, service: str, runlevel: int) -> bool`

=== SUBSYSTEM: Package Manager ===

MODULE 14 — Package Manager (`os/pkg/`):

72. Create `os/pkg/__init__.py`

73. Create `os/pkg/package.py`:
    - `Package` dataclass: name, version, description, dependencies, files, pre_install, post_install

74. Create `os/pkg/database.py`:
    - `PackageDatabase`:
      - `installed: dict[str, Package]`
      - `load(self, fs: FileSystem, path: str = "/var/lib/pkg/installed") -> None`
      - `save(self, fs: FileSystem) -> None`
      - `is_installed(self, name: str) -> bool`
      - `get_version(self, name: str) -> str | None`

75. Create `os/pkg/manager.py`:
    - `PackageManager`:
      - `__init__(self, fs: FileSystem)`
      - `db: PackageDatabase`
      - `install(self, package_file: str) -> bool` — from .pkg file
      - `remove(self, name: str) -> bool`
      - `upgrade(self, name: str, new_package: str) -> bool`
      - `resolve_dependencies(self, package: Package) -> list[Package]`
      - `verify_integrity(self, name: str) -> bool`

76. Create `os/pkg/bin/pkg.py`:
    - `pkg_main(args: list[str], fs: FileSystem, env: dict, stdout, stderr) -> int`
    - Subcommands: install, remove, update, search, list, info

=== SUBSYSTEM: Logging ===

MODULE 15 — Logging Daemon (`os/logd/`):

77. Create `os/logd/__init__.py`

78. Create `os/logd/logger.py`:
    - `LogEntry` dataclass: timestamp, facility, level, message, pid
    - `SyslogFacility` enum: KERN, USER, MAIL, DAEMON, AUTH, SYSLOG, LPR, NEWS, UUCP, CRON, AUTHPRIV, FTP, LOCAL0-7
    - `LogLevel` enum: EMERG, ALERT, CRIT, ERR, WARNING, NOTICE, INFO, DEBUG

79. Create `os/logd/daemon.py`:
    - `LogDaemon`:
      - `__init__(self, fs: FileSystem)`
      - `log_file: str = "/var/log/syslog"`
      - `facility_levels: dict[SyslogFacility, LogLevel]`
      - `log(self, entry: LogEntry) -> None`
      - `rotate_logs(self) -> None`
      - `read_logs(self, lines: int = 100) -> list[LogEntry]`
      - `clear_logs(self) -> None`

=== SUBSYSTEM: Network (Stub) ===

MODULE 16 — Network Stack (`os/net/`):

80. Create `os/net/__init__.py`

81. Create `os/net/socket.py`:
    - `Socket` class (stub):
      - `family: int`, `type: int`, `protocol: int`
      - `bind(self, address: tuple) -> bool`
      - `listen(self, backlog: int) -> bool`
      - `accept(self) -> tuple[Socket, tuple]`
      - `connect(self, address: tuple) -> bool`
      - `send(self, data: bytes) -> int`
      - `recv(self, bufsize: int) -> bytes`
      - `close(self) -> bool`

82. Create `os/net/stack.py`:
    - `NetworkStack` (stub):
      - `configure_interface(self, name: str, address: str, netmask: str) -> bool`
      - `add_route(self, destination: str, gateway: str) -> bool`
      - `resolve_hostname(self, hostname: str) -> str | None`

=== SUBSYSTEM: IPC ===

MODULE 17 — Inter-Process Communication (`os/ipc/`):

83. Create `os/ipc/__init__.py`

84. Create `os/ipc/pipe.py`:
    - `Pipe`:
      - `read_fd: int`, `write_fd: int`
      - `buffer: bytes` — internal buffer
      - `read(self, size: int) -> bytes`
      - `write(self, data: bytes) -> int`
      - `close_read(self) -> None`
      - `close_write(self) -> None`

85. Create `os/ipc/shared_memory.py`:
    - `SharedMemorySegment`:
      - `key: int`, `size: int`, `data: bytearray`
      - `attach(self, pid: int) -> bool`
      - `detach(self, pid: int) -> bool`
      - `read(self, offset: int, size: int) -> bytes`
      - `write(self, offset: int, data: bytes) -> int`

86. Create `os/ipc/semaphore.py`:
    - `Semaphore`:
      - `key: int`, `value: int`
      - `wait(self) -> None` — P operation
      - `signal(self) -> None` — V operation
      - `get_value(self) -> int`

87. Create `os/ipc/message_queue.py`:
    - `MessageQueue`:
      - `key: int`, `messages: list[tuple[int, bytes]]` — (type, data)
      - `send(self, mtype: int, data: bytes, block: bool = True) -> bool`
      - `receive(self, mtype: int, block: bool = True) -> tuple[int, bytes] | None`

=== SUBSYSTEM: Tests ===

MODULE 18 — Comprehensive Test Suite (`tests/`):

88. Create `tests/kernel/`:
    - `test_process.py` (4 tests): test_creation, test_states, test_memory, test_signals
    - `test_scheduler.py` (5 tests): test_round_robin, test_priority, test_fifo, test_multilevel, test_context_switch
    - `test_memory.py` (4 tests): test_allocate, test_free, test_page_table, test_address_translation
    - `test_syscalls.py` (4 tests): test_fork, test_exec, test_wait, test_exit
    - `test_signals.py` (3 tests): test_send, test_handler, test_pending

89. Create `tests/fs/`:
    - `test_inode.py` (4 tests): test_permissions, test_mode_string, test_types
    - `test_filesystem.py` (6 tests): test_create_file, test_create_dir, test_read_write, test_symlink, test_chmod, test_persistence
    - `test_directory.py` (3 tests): test_add_entry, test_remove, test_list
    - `test_bitmap.py` (3 tests): test_set_clear, test_find_zero, test_find_set

90. Create `tests/shell/`:
    - `test_lexer.py` (4 tests): test_tokens, test_quotes, test_escapes, test_variables
    - `test_parser.py` (3 tests): test_pipeline, test_redirects, test_background
    - `test_expansion.py` (3 tests): test_variables, test_tilde, test_glob

91. Create `tests/bin/`:
    - `test_ls.py` (3 tests): test_basic, test_long, test_all
    - `test_cat.py` (3 tests): test_basic, test_number, test_stdin
    - `test_grep.py` (3 tests): test_basic, test_ignore_case, test_invert
    - `test_wc.py` (3 tests): test_lines, test_words, test_bytes
    - `test_sort.py` (3 tests): test_basic, test_numeric, test_reverse
    - `test_cp.py` (2 tests): test_file, test_recursive
    - `test_mv.py` (2 tests): test_rename, test_move
    - `test_rm.py` (2 tests): test_file, test_recursive
    - `test_mkdir.py` (2 tests): test_basic, test_parents
    - `test_chmod.py` (2 tests): test_numeric, test_symbolic
    - `test_echo.py` (2 tests): test_basic, test_no_newline

92. Create `tests/vi/`:
    - `test_buffer.py` (3 tests): test_insert, test_delete, test_save_load
    - `test_editor.py` (3 tests): test_modes, test_movement, test_commands

93. Create `tests/users/`:
    - `test_passwd.py` (3 tests): test_load, test_lookup, test_add
    - `test_auth.py` (2 tests): test_authenticate, test_check_password

94. Create `tests/init/`:
    - `test_init.py` (2 tests): test_boot, test_services

95. Create `tests/pkg/`:
    - `test_manager.py` (3 tests): test_install, test_remove, test_dependencies

96. Create `tests/ipc/`:
    - `test_pipe.py` (3 tests): test_read_write, test_close, test_buffer
    - `test_shared_memory.py` (2 tests): test_attach, test_read_write
    - `test_semaphore.py` (2 tests): test_wait_signal, test_value

97. Create `tests/integration/`:
    - `test_boot_sequence.py` — full boot: init -> shell -> commands
    - `test_file_operations.py` — create, write, read, delete files
    - `test_process_lifecycle.py` — fork, exec, wait, exit
    - `test_shell_pipeline.py` — cat file | grep pattern | wc -l
    - `test_vi_workflow.py` — open, edit, save file

Run `python -m pytest tests/ -v` to verify ALL 200+ tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No external dependencies.
- File system is in-memory with optional persistence to disk.
- Scheduler is simulated (no real process preemption).
- Memory is simulated with page tables (no real virtual memory).
- Shell runs in the same Python process (no real subprocesses).
- Devices are stubs (no real hardware access).
- Network stack is stubbed (no real sockets).
- All timestamps use datetime module.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=15,
        name="MEGA-5: Operating System Simulation",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=WORKER_TIMEOUT,
        expected_test_count=200,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
