#!/usr/bin/env python3
"""Mega Tier 14: Full Social Platform Backend.

Complexity: 100-140 workers, ~280 files, ~18K LOC.
Task: Build a complete social platform backend with user auth, profiles, posts/feeds,
comments, likes/reactions, follow/unfollow, direct messages, groups/communities,
notifications, search, media handling, hashtags/trending, moderation, reports,
analytics, REST API, rate limiting, caching, email stub, privacy, block/mute,
and activity feed algorithm.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-mega-4"
WORKER_TIMEOUT = 1200

SCAFFOLD_FILES = {
    "social/__init__.py": '''\
"""ConnectHub — A full-featured social platform backend in pure Python."""

__version__ = "0.1.0"

from social.models.user import User
from social.models.post import Post
from social.models.comment import Comment

__all__ = ["User", "Post", "Comment"]
''',
    "social/models/__init__.py": '''\
"""Core models for the social platform."""

from social.models.user import User, UserStatus, AccountType
from social.models.post import Post, PostVisibility, PostType
from social.models.comment import Comment
from social.models.like import Like, ReactionType
from social.models.follow import Follow
from social.models.message import Message, MessageStatus
from social.models.group import Group, GroupMembership, GroupRole
from social.models.notification import Notification, NotificationType

__all__ = [
    "User", "UserStatus", "AccountType",
    "Post", "PostVisibility", "PostType",
    "Comment", "Like", "ReactionType",
    "Follow", "Message", "MessageStatus",
    "Group", "GroupMembership", "GroupRole",
    "Notification", "NotificationType",
]
''',
    "social/models/user.py": '''\
"""User model for the social platform."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class UserStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"
    BANNED = "banned"


class AccountType(Enum):
    PERSONAL = "personal"
    BUSINESS = "business"
    CREATOR = "creator"


@dataclass
class User:
    """A user in the social platform."""
    id: str
    username: str
    email: str
    password_hash: str = ""
    status: UserStatus = UserStatus.PENDING_VERIFICATION
    account_type: AccountType = AccountType.PERSONAL
    
    # Profile
    display_name: str = ""
    bio: str = ""
    location: str = ""
    website: str = ""
    avatar_url: str = ""
    banner_url: str = ""
    birth_date: datetime | None = None
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_active: datetime | None = None
    email_verified_at: datetime | None = None
    
    # Stats (denormalized)
    follower_count: int = 0
    following_count: int = 0
    post_count: int = 0
    
    # Settings
    is_private: bool = False
    allows_dms_from: str = "everyone"  # everyone, followers, none
    shows_activity_status: bool = True
    timezone: str = "UTC"
    locale: str = "en"
    
    metadata: dict = field(default_factory=dict)
''',
    "social/models/post.py": '''\
"""Post model for the social platform."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


class PostVisibility(Enum):
    PUBLIC = "public"
    FOLLOWERS = "followers"
    MENTIONED = "mentioned"
    PRIVATE = "private"


class PostType(Enum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    LINK = "link"
    POLL = "poll"
    REPOST = "repost"


@dataclass
class Post:
    """A post in the social platform."""
    id: str
    author_id: str
    content: str = ""
    post_type: PostType = PostType.TEXT
    visibility: PostVisibility = PostVisibility.PUBLIC
    
    # Media
    media_urls: list[str] = field(default_factory=list)
    thumbnail_url: str = ""
    
    # Engagement (denormalized)
    like_count: int = 0
    comment_count: int = 0
    repost_count: int = 0
    view_count: int = 0
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    edited: bool = False
    
    # Repost
    repost_of_id: str | None = None
    quote_content: str = ""  # Additional text on repost
    
    # Location
    location_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    
    # Tags
    mention_ids: list[str] = field(default_factory=list)
    hashtag_ids: list[str] = field(default_factory=list)
    
    metadata: dict = field(default_factory=dict)
''',
    "social/models/comment.py": '''\
"""Comment model for posts."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Comment:
    """A comment on a post."""
    id: str
    post_id: str
    author_id: str
    content: str = ""
    parent_id: str | None = None  # For nested replies
    
    # Engagement
    like_count: int = 0
    reply_count: int = 0
    
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    edited: bool = False
    
    mention_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
''',
    "social/models/like.py": '''\
"""Like/Reaction model."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ReactionType(Enum):
    LIKE = "like"
    LOVE = "love"
    HAHA = "haha"
    WOW = "wow"
    SAD = "sad"
    ANGRY = "angry"
    CARE = "care"


@dataclass
class Like:
    """A like or reaction on content."""
    id: str
    user_id: str
    target_type: str  # post, comment
    target_id: str
    reaction_type: ReactionType = ReactionType.LIKE
    created_at: datetime = field(default_factory=datetime.now)
''',
    "social/models/follow.py": '''\
"""Follow relationship model."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Follow:
    """A follow relationship between users."""
    id: str
    follower_id: str
    following_id: str
    created_at: datetime = field(default_factory=datetime.now)
    notifications_enabled: bool = True
''',
    "social/models/message.py": '''\
"""Direct message model."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MessageStatus(Enum):
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


@dataclass
class Message:
    """A direct message between users."""
    id: str
    conversation_id: str
    sender_id: str
    content: str = ""
    
    # Media
    media_urls: list[str] = field(default_factory=list)
    
    # Status
    status: MessageStatus = MessageStatus.SENDING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    read_at: datetime | None = None
    
    # Reply
    reply_to_id: str | None = None
    
    metadata: dict = field(default_factory=dict)
''',
    "social/models/group.py": '''\
"""Group/Community model."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class GroupRole(Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MODERATOR = "moderator"
    MEMBER = "member"


class GroupVisibility(Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    SECRET = "secret"


@dataclass
class Group:
    """A group or community."""
    id: str
    name: str
    description: str = ""
    visibility: GroupVisibility = GroupVisibility.PUBLIC
    
    # Media
    avatar_url: str = ""
    banner_url: str = ""
    
    # Stats
    member_count: int = 0
    post_count: int = 0
    
    # Settings
    requires_approval: bool = False
    only_admins_can_post: bool = False
    
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    created_by: str = ""
    
    metadata: dict = field(default_factory=dict)


@dataclass
class GroupMembership:
    """A user's membership in a group."""
    id: str
    group_id: str
    user_id: str
    role: GroupRole = GroupRole.MEMBER
    joined_at: datetime = field(default_factory=datetime.now)
    notifications_enabled: bool = True
''',
    "social/models/notification.py": '''\
"""Notification model."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class NotificationType(Enum):
    LIKE = "like"
    COMMENT = "comment"
    FOLLOW = "follow"
    MENTION = "mention"
    REPOST = "repost"
    MESSAGE = "message"
    GROUP_INVITE = "group_invite"
    GROUP_JOIN_REQUEST = "group_join_request"
    SYSTEM = "system"


@dataclass
class Notification:
    """A notification for a user."""
    id: str
    user_id: str
    type: NotificationType
    
    # Actor who triggered the notification
    actor_id: str | None = None
    
    # Target content
    target_type: str = ""  # post, comment, user, group, etc.
    target_id: str = ""
    
    # Content
    title: str = ""
    message: str = ""
    
    # Status
    read: bool = False
    clicked: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    read_at: datetime | None = None
    
    metadata: dict = field(default_factory=dict)
''',
    "tests/__init__.py": "",
    "tests/conftest.py": """\
import pytest
from datetime import datetime
from social.models.user import User, UserStatus, AccountType
from social.models.post import Post, PostVisibility, PostType
from social.models.comment import Comment


@pytest.fixture
def sample_user():
    return User(
        id="user-1",
        username="testuser",
        email="test@example.com",
        display_name="Test User",
        status=UserStatus.ACTIVE,
        account_type=AccountType.PERSONAL
    )


@pytest.fixture
def sample_post():
    return Post(
        id="post-1",
        author_id="user-1",
        content="Hello, world!",
        post_type=PostType.TEXT,
        visibility=PostVisibility.PUBLIC
    )


@pytest.fixture
def sample_comment():
    return Comment(
        id="comment-1",
        post_id="post-1",
        author_id="user-2",
        content="Great post!"
    )
""",
    "tests/test_user.py": """\
from social.models.user import User, UserStatus, AccountType


def test_user_creation():
    user = User(id="u1", username="alice", email="alice@test.com")
    assert user.status == UserStatus.PENDING_VERIFICATION
    assert user.account_type == AccountType.PERSONAL


def test_user_defaults():
    user = User(id="u1", username="bob", email="bob@test.com")
    assert user.follower_count == 0
    assert user.following_count == 0
    assert not user.is_private


def test_user_status_values():
    assert UserStatus.ACTIVE.value == "active"
    assert UserStatus.BANNED.value == "banned"
""",
    "tests/test_post.py": """\
from social.models.post import Post, PostVisibility, PostType


def test_post_creation():
    post = Post(id="p1", author_id="u1", content="Test")
    assert post.visibility == PostVisibility.PUBLIC
    assert post.post_type == PostType.TEXT


def test_post_repost():
    post = Post(id="p1", author_id="u1", repost_of_id="p0")
    assert post.repost_of_id == "p0"


def test_post_visibility_values():
    assert PostVisibility.PUBLIC.value == "public"
    assert PostVisibility.PRIVATE.value == "private"
""",
}

INSTRUCTIONS = """\
Build a FULL-FEATURED SOCIAL PLATFORM BACKEND called "social". Use ONLY Python stdlib.
No external dependencies. This is a comprehensive social network backend comparable
to Twitter/X, Facebook, or Instagram with user management, content feeds, engagement,
messaging, groups, notifications, search, moderation, and analytics.

=== SUBSYSTEM: Core Infrastructure ===

MODULE 1 — Database Layer (`social/db/`):

1. Create `social/db/__init__.py`

2. Create `social/db/connection.py`:
   - `DatabaseConnection` abstract base:
     - `connect(self) -> None`
     - `disconnect(self) -> None`
     - `execute(self, query: str, params: tuple = ()) -> list[dict]`
     - `execute_many(self, query: str, params_list: list) -> int` — rows affected
     - `last_insert_id(self) -> int | None`
     - `begin_transaction(self) -> None`
     - `commit(self) -> None`
     - `rollback(self) -> None`

3. Create `social/db/sqlite_backend.py`:
   - `SQLiteConnection(DatabaseConnection)`:
     - `__init__(self, db_path: str)`
     - Full SQLite implementation using sqlite3 module
     - Connection pooling with thread-local storage
     - Row factory returning dicts

4. Create `social/db/migrations.py`:
   - `MigrationManager`:
     - `__init__(self, connection: DatabaseConnection)`
     - `create_migrations_table(self) -> None`
     - `get_applied_migrations(self) -> list[str]`
     - `apply_migration(self, name: str, sql: str) -> None`
     - `rollback_migration(self, name: str) -> None`
     - `is_migration_applied(self, name: str) -> bool`

5. Create `social/db/repository.py`:
   - `Repository` base class:
     - `__init__(self, connection: DatabaseConnection)`
     - `table_name: str` — abstract
     - `find_by_id(self, id: str) -> dict | None`
     - `find_all(self, limit: int = 100, offset: int = 0) -> list[dict]`
     - `find_by(self, **conditions) -> list[dict]`
     - `create(self, data: dict) -> dict`
     - `update(self, id: str, data: dict) -> dict | None`
     - `delete(self, id: str) -> bool`
     - `count(self) -> int`
     - `exists(self, id: str) -> bool`

MODULE 2 — Caching Layer (`social/cache/`):

6. Create `social/cache/__init__.py`

7. Create `social/cache/backend.py`:
   - `CacheBackend` base:
     - `get(self, key: str) -> any | None`
     - `set(self, key: str, value: any, ttl: int | None = None) -> bool`
     - `delete(self, key: str) -> bool`
     - `exists(self, key: str) -> bool`
     - `flush(self) -> None`

8. Create `social/cache/memory.py`:
   - `InMemoryCache(CacheBackend)`:
     - Thread-safe with threading.RLock
     - TTL support with expiration tracking
     - LRU eviction when size limit reached
     - `get_stats(self) -> dict` — hits, misses, size

9. Create `social/cache/decorator.py`:
   - `cached(ttl: int = 300, key_fn: Callable | None = None)` — decorator for caching function results
   - `cache_evict(key_pattern: str)` — decorator to evict cache on function call

MODULE 3 — Event Bus (`social/events/`):

10. Create `social/events/__init__.py`

11. Create `social/events/bus.py`:
    - `Event` dataclass: id, type, payload, timestamp, source
    - `EventBus`:
      - `subscribe(self, event_type: str, handler: Callable) -> str` — return subscription id
      - `unsubscribe(self, subscription_id: str) -> bool`
      - `publish(self, event: Event) -> None` — async dispatch
      - `publish_sync(self, event: Event) -> None` — immediate dispatch

12. Create `social/events/handlers.py`:
    - Event handlers: UserRegisteredHandler, PostCreatedHandler, LikeReceivedHandler, etc.

=== SUBSYSTEM: User Management ===

MODULE 4 — User Repository (`social/repos/user_repo.py`):

13. Create `social/repos/__init__.py`

14. Create `social/repos/user_repo.py`:
    - `UserRepository(Repository)`:
      - `find_by_username(self, username: str) -> User | None`
      - `find_by_email(self, email: str) -> User | None`
      - `search_users(self, query: str, limit: int = 20) -> list[User]` — search by username/display_name
      - `find_by_usernames(self, usernames: list[str]) -> list[User]`
      - `update_stats(self, user_id: str, follower_delta: int = 0, following_delta: int = 0, post_delta: int = 0) -> bool`
      - `update_last_active(self, user_id: str) -> bool`
      - `find_suggested_users(self, user_id: str, limit: int = 10) -> list[User]` — users not followed
      - `find_verified_users(self, limit: int = 50) -> list[User]`

MODULE 5 — Authentication (`social/auth/`):

15. Create `social/auth/__init__.py`

16. Create `social/auth/password.py`:
    - `hash_password(password: str) -> str` — PBKDF2-HMAC-SHA256
    - `verify_password(password: str, hashed: str) -> bool`

17. Create `social/auth/jwt.py`:
    - `JWTToken` dataclass: token, user_id, expires_at
    - `create_access_token(user_id: str, secret: str, expires_hours: int = 24) -> str`
    - `create_refresh_token(user_id: str, secret: str, expires_days: int = 30) -> str`
    - `decode_token(token: str, secret: str) -> dict | None`
    - `verify_token(token: str, secret: str) -> JWTToken | None`

18. Create `social/auth/service.py`:
    - `AuthService`:
      - `register(self, username: str, email: str, password: str, display_name: str = "") -> tuple[User, str]` — return user + access token
      - `login(self, username_or_email: str, password: str) -> tuple[User, str] | None`
      - `logout(self, token: str) -> bool`
      - `refresh_token(self, refresh_token: str) -> str | None`
      - `change_password(self, user_id: str, old_password: str, new_password: str) -> bool`
      - `request_password_reset(self, email: str) -> str | None` — return reset token
      - `reset_password(self, reset_token: str, new_password: str) -> bool`
      - `verify_email(self, verification_token: str) -> bool`

MODULE 6 — Profile Service (`social/services/profile_service.py`):

19. Create `social/services/__init__.py`

20. Create `social/services/profile_service.py`:
    - `ProfileService`:
      - `get_profile(self, user_id: str, requesting_user_id: str | None = None) -> dict | None` — full profile with stats
      - `update_profile(self, user_id: str, updates: dict) -> User | None` — bio, display_name, etc.
      - `update_avatar(self, user_id: str, image_data: bytes) -> str | None` — return URL
      - `update_banner(self, user_id: str, image_data: bytes) -> str | None`
      - `search_profiles(self, query: str, limit: int = 20) -> list[dict]`
      - `get_followers(self, user_id: str, limit: int = 20, offset: int = 0) -> list[User]`
      - `get_following(self, user_id: str, limit: int = 20, offset: int = 0) -> list[User]`
      - `is_following(self, follower_id: str, following_id: str) -> bool`

=== SUBSYSTEM: Content (Posts/Feed) ===

MODULE 7 — Post Repository (`social/repos/post_repo.py`):

21. Create `social/repos/post_repo.py`:
    - `PostRepository(Repository)`:
      - `find_by_author(self, author_id: str, limit: int = 20, offset: int = 0) -> list[Post]`
      - `find_by_authors(self, author_ids: list[str], limit: int = 20, offset: int = 0) -> list[Post]` — for feed
      - `find_public_posts(self, limit: int = 20, offset: int = 0) -> list[Post]`
      - `find_by_hashtag(self, hashtag: str, limit: int = 20, offset: int = 0) -> list[Post]`
      - `find_by_mention(self, user_id: str, limit: int = 20, offset: int = 0) -> list[Post]`
      - `search_posts(self, query: str, limit: int = 20) -> list[Post]` — full-text search
      - `update_stats(self, post_id: str, like_delta: int = 0, comment_delta: int = 0, repost_delta: int = 0, view_delta: int = 0) -> bool`
      - `find_reposts(self, post_id: str, limit: int = 20) -> list[Post]`
      - `delete_by_author(self, author_id: str) -> int` — delete all user's posts

MODULE 8 — Feed Service (`social/services/feed_service.py`):

22. Create `social/services/feed_service.py`:
    - `FeedService`:
      - `__init__(self, post_repo: PostRepository, follow_repo, cache: CacheBackend)`
      - `get_home_feed(self, user_id: str, limit: int = 20, offset: int = 0) -> list[Post]` — posts from followed users
      - `get_user_feed(self, user_id: str, target_user_id: str, limit: int = 20) -> list[Post]` — posts by specific user
      - `get_explore_feed(self, user_id: str | None = None, limit: int = 20) -> list[Post]` — trending/public posts
      - `get_liked_feed(self, user_id: str, limit: int = 20) -> list[Post]` — posts liked by user
      - `invalidate_feed_cache(self, user_id: str) -> None`
      - `generate_feed_algorithm(self, user_id: str, candidates: list[Post]) -> list[Post]` — simple ranking: recency + engagement

MODULE 9 — Post Service (`social/services/post_service.py`):

23. Create `social/services/post_service.py`:
    - `PostService`:
      - `create_post(self, author_id: str, content: str, visibility: PostVisibility, media: list[bytes] | None = None, location: dict | None = None) -> Post`
      - `get_post(self, post_id: str, requesting_user_id: str | None = None) -> Post | None`
      - `update_post(self, post_id: str, user_id: str, content: str) -> Post | None`
      - `delete_post(self, post_id: str, user_id: str) -> bool`
      - `repost(self, user_id: str, post_id: str, quote_content: str = "") -> Post | None`
      - `get_thread(self, post_id: str) -> list[Post]` — post + its reposts
      - `increment_view_count(self, post_id: str) -> None`
      - `can_view(self, post: Post, user_id: str | None) -> bool` — visibility check

=== SUBSYSTEM: Engagement ===

MODULE 10 — Follow Repository (`social/repos/follow_repo.py`):

24. Create `social/repos/follow_repo.py`:
    - `FollowRepository(Repository)`:
      - `find_followers(self, user_id: str, limit: int = 20, offset: int = 0) -> list[Follow]`
      - `find_following(self, user_id: str, limit: int = 20, offset: int = 0) -> list[Follow]`
      - `find_mutual_follows(self, user_id: str, other_user_id: str) -> list[str]` — user IDs
      - `is_following(self, follower_id: str, following_id: str) -> bool`
      - `get_follower_count(self, user_id: str) -> int`
      - `get_following_count(self, user_id: str) -> int`
      - `get_follow_stats(self, user_id: str) -> tuple[int, int]` — followers, following

MODULE 11 — Follow Service (`social/services/follow_service.py`):

25. Create `social/services/follow_service.py`:
    - `FollowService`:
      - `follow(self, follower_id: str, following_id: str) -> Follow | None`
      - `unfollow(self, follower_id: str, following_id: str) -> bool`
      - `get_followers(self, user_id: str, limit: int = 20, offset: int = 0) -> list[User]`
      - `get_following(self, user_id: str, limit: int = 20, offset: int = 0) -> list[User]`
      - `get_follow_status(self, follower_id: str, following_id: str) -> str` — "none", "following", "pending"
      - `toggle_notifications(self, follower_id: str, following_id: str, enabled: bool) -> bool`

MODULE 12 — Like Repository (`social/repos/like_repo.py`):

26. Create `social/repos/like_repo.py`:
    - `LikeRepository(Repository)`:
      - `find_by_target(self, target_type: str, target_id: str, limit: int = 50) -> list[Like]`
      - `find_by_user(self, user_id: str, limit: int = 50, offset: int = 0) -> list[Like]`
      - `find_by_user_and_target(self, user_id: str, target_type: str, target_id: str) -> Like | None`
      - `get_like_count(self, target_type: str, target_id: str) -> int`
      - `get_reaction_counts(self, target_type: str, target_id: str) -> dict[ReactionType, int]`
      - `has_liked(self, user_id: str, target_type: str, target_id: str) -> bool`

MODULE 13 — Like Service (`social/services/like_service.py`):

27. Create `social/services/like_service.py`:
    - `LikeService`:
      - `like(self, user_id: str, target_type: str, target_id: str, reaction_type: ReactionType = ReactionType.LIKE) -> Like`
      - `unlike(self, user_id: str, target_type: str, target_id: str) -> bool`
      - `get_likes(self, target_type: str, target_id: str, limit: int = 50) -> list[Like]`
      - `get_reaction_summary(self, target_type: str, target_id: str) -> dict`
      - `get_user_liked_posts(self, user_id: str, limit: int = 20) -> list[str]` — post IDs

MODULE 14 — Comment Repository (`social/repos/comment_repo.py`):

28. Create `social/repos/comment_repo.py`:
    - `CommentRepository(Repository)`:
      - `find_by_post(self, post_id: str, limit: int = 50, offset: int = 0) -> list[Comment]`
      - `find_replies(self, comment_id: str, limit: int = 50) -> list[Comment]` — nested replies
      - `find_by_author(self, author_id: str, limit: int = 20) -> list[Comment]`
      - `count_by_post(self, post_id: str) -> int`
      - `update_reply_count(self, comment_id: str, delta: int) -> bool`
      - `delete_by_post(self, post_id: str) -> int` — delete all comments on post

MODULE 15 — Comment Service (`social/services/comment_service.py`):

29. Create `social/services/comment_service.py`:
    - `CommentService`:
      - `create_comment(self, post_id: str, author_id: str, content: str, parent_id: str | None = None) -> Comment`
      - `get_comments(self, post_id: str, limit: int = 50, offset: int = 0) -> list[Comment]`
      - `get_thread(self, comment_id: str) -> list[Comment]` — comment + nested replies
      - `update_comment(self, comment_id: str, user_id: str, content: str) -> Comment | None`
      - `delete_comment(self, comment_id: str, user_id: str) -> bool`

=== SUBSYSTEM: Direct Messages ===

MODULE 16 — Message Repository (`social/repos/message_repo.py`):

30. Create `social/repos/message_repo.py`:
    - `MessageRepository(Repository)`:
      - `find_by_conversation(self, conversation_id: str, limit: int = 50, before_id: str | None = None) -> list[Message]` — paginated
      - `find_by_sender(self, sender_id: str, limit: int = 20) -> list[Message]`
      - `find_unread_by_user(self, user_id: str) -> list[Message]`
      - `count_unread(self, user_id: str) -> int`
      - `mark_as_read(self, message_id: str) -> bool`
      - `mark_conversation_as_read(self, conversation_id: str, user_id: str) -> int` — count marked
      - `update_status(self, message_id: str, status: MessageStatus) -> bool`

MODULE 17 — Conversation Repository (`social/repos/conversation_repo.py`):

31. Create `social/repos/conversation_repo.py`:
    - `Conversation` dataclass: id, participants (list), created_at, updated_at, last_message_at, last_message_preview
    - `ConversationRepository`:
      - `find_by_participants(self, user_ids: list[str]) -> Conversation | None`
      - `find_by_user(self, user_id: str, limit: int = 20) -> list[Conversation]` — with last message
      - `add_participant(self, conversation_id: str, user_id: str) -> bool`
      - `remove_participant(self, conversation_id: str, user_id: str) -> bool`
      - `update_last_message(self, conversation_id: str, preview: str, timestamp: datetime) -> bool`

MODULE 18 — Message Service (`social/services/message_service.py`):

32. Create `social/services/message_service.py`:
    - `MessageService`:
      - `send_message(self, sender_id: str, recipient_id: str, content: str, media: list[bytes] | None = None, reply_to_id: str | None = None) -> Message`
      - `send_group_message(self, sender_id: str, conversation_id: str, content: str) -> Message`
      - `get_conversation(self, conversation_id: str, user_id: str) -> dict | None`
      - `get_or_create_conversation(self, user_id: str, other_user_id: str) -> Conversation`
      - `get_messages(self, conversation_id: str, user_id: str, limit: int = 50, before_id: str | None = None) -> list[Message]`
      - `mark_as_read(self, message_id: str, user_id: str) -> bool`
      - `delete_message(self, message_id: str, user_id: str) -> bool`
      - `can_message(self, sender_id: str, recipient_id: str) -> bool` — check privacy settings

=== SUBSYSTEM: Groups ===

MODULE 19 — Group Repository (`social/repos/group_repo.py`):

33. Create `social/repos/group_repo.py`:
    - `GroupRepository(Repository)`:
      - `search_groups(self, query: str, limit: int = 20) -> list[Group]`
      - `find_by_member(self, user_id: str, limit: int = 20) -> list[Group]`
      - `find_public_groups(self, limit: int = 20, offset: int = 0) -> list[Group]`
      - `update_member_count(self, group_id: str, delta: int) -> bool`
      - `update_post_count(self, group_id: str, delta: int) -> bool`

34. Create `social/repos/group_membership_repo.py`:
    - `GroupMembershipRepository(Repository)`:
      - `find_by_group(self, group_id: str, limit: int = 50) -> list[GroupMembership]`
      - `find_by_user(self, user_id: str, limit: int = 20) -> list[GroupMembership]`
      - `find_by_group_and_user(self, group_id: str, user_id: str) -> GroupMembership | None`
      - `get_member_count(self, group_id: str) -> int`
      - `get_members_by_role(self, group_id: str, role: GroupRole) -> list[GroupMembership]`
      - `update_role(self, group_id: str, user_id: str, new_role: GroupRole) -> bool`

MODULE 20 — Group Service (`social/services/group_service.py`):

35. Create `social/services/group_service.py`:
    - `GroupService`:
      - `create_group(self, name: str, description: str, creator_id: str, visibility: GroupVisibility) -> Group`
      - `get_group(self, group_id: str, user_id: str | None = None) -> Group | None`
      - `update_group(self, group_id: str, user_id: str, updates: dict) -> Group | None`
      - `delete_group(self, group_id: str, user_id: str) -> bool`
      - `join_group(self, group_id: str, user_id: str) -> GroupMembership | None`
      - `leave_group(self, group_id: str, user_id: str) -> bool`
      - `invite_member(self, group_id: str, inviter_id: str, invitee_id: str) -> bool`
      - `approve_join_request(self, group_id: str, admin_id: str, user_id: str) -> bool`
      - `remove_member(self, group_id: str, admin_id: str, user_id: str) -> bool`
      - `update_member_role(self, group_id: str, admin_id: str, user_id: str, new_role: GroupRole) -> bool`
      - `get_members(self, group_id: str, limit: int = 50) -> list[dict]`
      - `is_member(self, group_id: str, user_id: str) -> bool`
      - `is_admin(self, group_id: str, user_id: str) -> bool`

=== SUBSYSTEM: Notifications ===

MODULE 21 — Notification Repository (`social/repos/notification_repo.py`):

36. Create `social/repos/notification_repo.py`:
    - `NotificationRepository(Repository)`:
      - `find_by_user(self, user_id: str, limit: int = 50, offset: int = 0) -> list[Notification]`
      - `find_unread_by_user(self, user_id: str, limit: int = 50) -> list[Notification]`
      - `count_unread(self, user_id: str) -> int`
      - `mark_as_read(self, notification_id: str) -> bool`
      - `mark_all_as_read(self, user_id: str) -> int` — count marked
      - `delete_old_notifications(self, days: int = 30) -> int` — cleanup

MODULE 22 — Notification Service (`social/services/notification_service.py`):

37. Create `social/services/notification_service.py`:
    - `NotificationService`:
      - `create_notification(self, user_id: str, type: NotificationType, actor_id: str | None, target_type: str, target_id: str, title: str = "", message: str = "") -> Notification`
      - `get_notifications(self, user_id: str, limit: int = 50, offset: int = 0) -> list[Notification]`
      - `get_unread_count(self, user_id: str) -> int`
      - `mark_as_read(self, notification_id: str, user_id: str) -> bool`
      - `mark_all_as_read(self, user_id: str) -> int`
      - `delete_notification(self, notification_id: str, user_id: str) -> bool`
      - Event handlers: on_like, on_comment, on_follow, on_mention

=== SUBSYSTEM: Search ===

MODULE 23 — Search (`social/search/`):

38. Create `social/search/__init__.py`

39. Create `social/search/indexer.py`:
    - `SearchIndexer`:
      - `index_post(self, post: Post) -> None` — extract text, hashtags, mentions
      - `index_user(self, user: User) -> None`
      - `remove_from_index(self, doc_type: str, doc_id: str) -> None`
      - Simple inverted index: word -> list of (doc_type, doc_id, positions)

40. Create `social/search/service.py`:
    - `SearchService`:
      - `search_users(self, query: str, limit: int = 20) -> list[User]`
      - `search_posts(self, query: str, limit: int = 20) -> list[Post]`
      - `search_groups(self, query: str, limit: int = 20) -> list[Group]`
      - `search_all(self, query: str, limit: int = 20) -> dict[str, list]`
      - `get_hashtag_posts(self, hashtag: str, limit: int = 20) -> list[Post]`
      - `get_trending_hashtags(self, limit: int = 10) -> list[tuple[str, int]]` — hashtag + count
      - `autocomplete(self, prefix: str, limit: int = 10) -> list[str]`

MODULE 24 — Hashtag Service (`social/services/hashtag_service.py`):

41. Create `social/services/hashtag_service.py`:
    - `HashtagService`:
      - `extract_hashtags(self, text: str) -> list[str]`
      - `normalize_hashtag(self, hashtag: str) -> str` — lowercase, remove leading #
      - `get_or_create_hashtag(self, normalized: str) -> str` — return hashtag ID
      - `get_trending(self, hours: int = 24, limit: int = 10) -> list[tuple[str, int]]`
      - `get_posts_with_hashtag(self, hashtag: str, limit: int = 20) -> list[str]` — post IDs

=== SUBSYSTEM: Privacy & Moderation ===

MODULE 25 — Privacy (`social/privacy/`):

42. Create `social/privacy/__init__.py`

43. Create `social/privacy/settings.py`:
    - `PrivacySettings` dataclass: user_id, is_private, allows_dms, show_activity, etc.
    - `PrivacyService`:
      - `get_settings(self, user_id: str) -> PrivacySettings`
      - `update_settings(self, user_id: str, settings: dict) -> PrivacySettings`
      - `can_view_profile(self, viewer_id: str | None, profile_user_id: str) -> bool`
      - `can_view_posts(self, viewer_id: str | None, profile_user_id: str) -> bool`
      - `can_send_message(self, sender_id: str, recipient_id: str) -> bool`

44. Create `social/privacy/block_repo.py`:
    - `Block` dataclass: blocker_id, blocked_id, created_at
    - `BlockRepository`:
      - `is_blocked(self, blocker_id: str, blocked_id: str) -> bool`
      - `is_blocked_either_way(self, user_a: str, user_b: str) -> bool`
      - `get_blocked_users(self, blocker_id: str) -> list[str]`
      - `block(self, blocker_id: str, blocked_id: str) -> Block`
      - `unblock(self, blocker_id: str, blocked_id: str) -> bool`

45. Create `social/privacy/mute_repo.py`:
    - `Mute` dataclass: muter_id, muted_id, mute_posts: bool, mute_stories: bool, created_at
    - `MuteRepository`:
      - `is_muted(self, muter_id: str, muted_id: str) -> bool`
      - `mute(self, muter_id: str, muted_id: str, mute_posts: bool = True, mute_stories: bool = True) -> Mute`
      - `unmute(self, muter_id: str, muted_id: str) -> bool`

46. Create `social/privacy/service.py`:
    - `BlockMuteService`:
      - `block_user(self, blocker_id: str, blocked_id: str) -> bool`
      - `unblock_user(self, blocker_id: str, blocked_id: str) -> bool`
      - `mute_user(self, muter_id: str, muted_id: str) -> bool`
      - `unmute_user(self, muter_id: str, muted_id: str) -> bool`
      - `is_blocked(self, user_a: str, user_b: str) -> bool`
      - `is_muted(self, muter_id: str, muted_id: str) -> bool`
      - `filter_blocked_content(self, user_id: str, content_list: list) -> list` — remove blocked users' content

MODULE 26 — Moderation (`social/moderation/`):

47. Create `social/moderation/__init__.py`

48. Create `social/moderation/report_repo.py`:
    - `Report` dataclass: id, reporter_id, target_type, target_id, reason, description, status, created_at, resolved_at, resolved_by, action_taken
    - `ReportStatus` enum: PENDING, INVESTIGATING, RESOLVED, DISMISSED
    - `ReportRepository`:
      - `find_pending(self, limit: int = 50) -> list[Report]`
      - `find_by_reporter(self, reporter_id: str) -> list[Report]`
      - `find_by_target(self, target_type: str, target_id: str) -> list[Report]`
      - `update_status(self, report_id: str, status: ReportStatus, resolved_by: str, action: str) -> bool`

49. Create `social/moderation/service.py`:
    - `ModerationService`:
      - `report_content(self, reporter_id: str, target_type: str, target_id: str, reason: str, description: str = "") -> Report`
      - `get_pending_reports(self, admin_id: str, limit: int = 50) -> list[Report]`
      - `resolve_report(self, report_id: str, admin_id: str, action: str, notes: str = "") -> bool`
      - `take_action(self, target_type: str, target_id: str, action: str) -> bool` — remove, warn, suspend
      - `check_content_policy(self, content: str) -> tuple[bool, list[str]]` — returns (is_violation, reasons)

=== SUBSYSTEM: Media (Stub) ===

MODULE 27 — Media (`social/media/`):

50. Create `social/media/__init__.py`

51. Create `social/media/storage.py`:
    - `MediaStorage` (stub):
      - `store(self, data: bytes, filename: str, content_type: str) -> str` — return URL
      - `delete(self, url: str) -> bool`
      - `get_url(self, media_id: str) -> str`

52. Create `social/media/service.py`:
    - `MediaService`:
      - `upload_image(self, data: bytes, user_id: str) -> str | None` — return URL
      - `upload_video(self, data: bytes, user_id: str) -> str | None`
      - `validate_image(self, data: bytes) -> bool` — check format, size
      - `generate_thumbnail(self, image_data: bytes, max_size: tuple = (300, 300)) -> bytes`

=== SUBSYSTEM: Rate Limiting ===

MODULE 28 — Rate Limiting (`social/ratelimit/`):

53. Create `social/ratelimit/__init__.py`

54. Create `social/ratelimit/limiter.py`:
    - `RateLimiter`:
      - `__init__(self, backend: CacheBackend)`
      - `is_allowed(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]` — (allowed, remaining, reset_time)
      - `check_rate_limit(self, identifier: str, action: str) -> tuple[bool, dict]`
    - `RateLimitExceeded` exception

55. Create `social/ratelimit/middleware.py`:
    - `RateLimitMiddleware`:
      - Rate limits by: IP address, user ID, action type
      - Configurable limits per endpoint

=== SUBSYSTEM: Email (Stub) ===

MODULE 29 — Email (`social/email/`):

56. Create `social/email/__init__.py`

57. Create `social/email/service.py`:
    - `EmailService` (stub):
      - `send_email(self, to: str, subject: str, body: str, html: bool = False) -> bool`
      - `send_verification_email(self, user: User, token: str) -> bool`
      - `send_password_reset_email(self, user: User, token: str) -> bool`
      - `send_notification_email(self, user: User, notification: Notification) -> bool`

=== SUBSYSTEM: Analytics ===

MODULE 30 — Analytics (`social/analytics/`):

58. Create `social/analytics/__init__.py`

59. Create `social/analytics/collector.py`:
    - `AnalyticsCollector`:
      - `track_event(self, event_type: str, user_id: str | None, data: dict) -> None`
      - `track_page_view(self, user_id: str | None, path: str) -> None`
      - `track_engagement(self, user_id: str, action: str, target_type: str, target_id: str) -> None`

60. Create `social/analytics/reports.py`:
    - `AnalyticsReports`:
      - `get_daily_active_users(self, days: int = 30) -> list[tuple[str, int]]` — date, count
      - `get_monthly_active_users(self, months: int = 12) -> list[tuple[str, int]]`
      - `get_post_engagement_stats(self, post_id: str) -> dict`
      - `get_user_growth(self, days: int = 30) -> list[tuple[str, int]]`
      - `get_top_posts(self, hours: int = 24, limit: int = 10) -> list[str]` — post IDs

=== SUBSYSTEM: REST API ===

MODULE 31 — API (`social/api/`):

61. Create `social/api/__init__.py`

62. Create `social/api/middleware.py`:
    - `AuthMiddleware` — extract and verify JWT
    - `CORSMiddleware` — CORS headers
    - `LoggingMiddleware` — request/response logging
    - `ErrorMiddleware` — error handling and formatting

63. Create `social/api/routes/auth.py`:
    - `AuthRoutes`:
      - `register(request) -> Response`
      - `login(request) -> Response`
      - `logout(request) -> Response`
      - `refresh(request) -> Response`
      - `forgot_password(request) -> Response`
      - `reset_password(request) -> Response`
      - `verify_email(request) -> Response`

64. Create `social/api/routes/users.py`:
    - `UserRoutes`:
      - `get_profile(request, user_id) -> Response`
      - `update_profile(request) -> Response`
      - `get_followers(request, user_id) -> Response`
      - `get_following(request, user_id) -> Response`
      - `follow(request, user_id) -> Response`
      - `unfollow(request, user_id) -> Response`
      - `search_users(request) -> Response`

65. Create `social/api/routes/posts.py`:
    - `PostRoutes`:
      - `create_post(request) -> Response`
      - `get_feed(request) -> Response`
      - `get_user_posts(request, user_id) -> Response`
      - `get_post(request, post_id) -> Response`
      - `update_post(request, post_id) -> Response`
      - `delete_post(request, post_id) -> Response`
      - `like_post(request, post_id) -> Response`
      - `unlike_post(request, post_id) -> Response`

66. Create `social/api/routes/comments.py`:
    - `CommentRoutes`:
      - `create_comment(request, post_id) -> Response`
      - `get_comments(request, post_id) -> Response`
      - `update_comment(request, comment_id) -> Response`
      - `delete_comment(request, comment_id) -> Response`
      - `like_comment(request, comment_id) -> Response`

67. Create `social/api/routes/messages.py`:
    - `MessageRoutes`:
      - `get_conversations(request) -> Response`
      - `get_messages(request, conversation_id) -> Response`
      - `send_message(request) -> Response`
      - `mark_read(request, message_id) -> Response`

68. Create `social/api/routes/groups.py`:
    - `GroupRoutes`:
      - `create_group(request) -> Response`
      - `get_group(request, group_id) -> Response`
      - `join_group(request, group_id) -> Response`
      - `leave_group(request, group_id) -> Response`
      - `get_group_members(request, group_id) -> Response`

69. Create `social/api/routes/notifications.py`:
    - `NotificationRoutes`:
      - `get_notifications(request) -> Response`
      - `mark_read(request, notification_id) -> Response`
      - `mark_all_read(request) -> Response`

70. Create `social/api/routes/search.py`:
    - `SearchRoutes`:
      - `search(request) -> Response`
      - `autocomplete(request) -> Response`
      - `trending_hashtags(request) -> Response`

71. Create `social/api/server.py`:
    - `APIServer`:
      - `__init__(self, host: str = "localhost", port: int = 8000)`
      - `register_routes(self) -> None`
      - `handle_request(self, request: dict) -> dict`
      - `serve_forever(self) -> None` — using http.server

=== SUBSYSTEM: Tests ===

MODULE 32 — Test Suite (`tests/`):

72. Create `tests/db/`:
    - `test_connection.py` (3 tests): test_connect, test_execute, test_transaction
    - `test_migrations.py` (2 tests): test_apply, test_rollback

73. Create `tests/repos/`:
    - `test_user_repo.py` (5 tests): test_find_by_username, test_search, test_update_stats
    - `test_post_repo.py` (5 tests): test_find_by_author, test_search_posts, test_update_stats
    - `test_follow_repo.py` (4 tests): test_find_followers, test_is_following, test_get_counts
    - `test_like_repo.py` (4 tests): test_find_by_target, test_has_liked, test_get_counts
    - `test_comment_repo.py` (4 tests): test_find_by_post, test_replies, test_count
    - `test_message_repo.py` (4 tests): test_find_by_conversation, test_unread, test_mark_read
    - `test_group_repo.py` (3 tests): test_find_by_member, test_search, test_update_counts
    - `test_notification_repo.py` (4 tests): test_find_by_user, test_unread_count, test_mark_all_read

74. Create `tests/services/`:
    - `test_auth_service.py` (4 tests): test_register, test_login, test_refresh, test_password_reset
    - `test_feed_service.py` (3 tests): test_home_feed, test_explore_feed, test_user_feed
    - `test_post_service.py` (4 tests): test_create, test_get, test_update, test_delete
    - `test_follow_service.py` (3 tests): test_follow, test_unfollow, test_status
    - `test_like_service.py` (3 tests): test_like, test_unlike, test_summary
    - `test_message_service.py` (3 tests): test_send, test_get_conversation, test_mark_read
    - `test_search_service.py` (3 tests): test_search_users, test_search_posts, test_hashtags
    - `test_privacy_service.py` (3 tests): test_can_view, test_can_message, test_filter_blocked

75. Create `tests/api/`:
    - `test_auth_routes.py` (4 tests): test_register, test_login, test_logout, test_refresh
    - `test_user_routes.py` (4 tests): test_get_profile, test_follow, test_search
    - `test_post_routes.py` (4 tests): test_create, test_get_feed, test_like, test_delete

76. Create `tests/integration/`:
    - `test_user_flow.py` — full user journey: register, post, follow, like, comment
    - `test_privacy_flow.py` — private account, follow request, content visibility
    - `test_messaging_flow.py` — start conversation, send messages, read receipts
    - `test_group_flow.py` — create group, invite, post in group

Run `python -m pytest tests/ -v` to verify ALL 140+ tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No Flask, Django, FastAPI, SQLAlchemy, Redis, Celery.
- HTTP server uses http.server from stdlib.
- Database is SQLite using sqlite3 module.
- Cache is in-memory with optional file backing.
- Media storage is stubbed (returns fake URLs).
- Email is stubbed (prints to console/logs).
- Rate limiting uses in-memory or file storage.
- All datetime operations use timezone-aware datetimes.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=14,
        name="MEGA-4: Social Platform Backend",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=WORKER_TIMEOUT,
        expected_test_count=140,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
