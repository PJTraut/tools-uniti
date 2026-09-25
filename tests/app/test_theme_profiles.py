import json
from dataclasses import replace

import pytest


def profiles():
    from uniti.app.theme_profiles import packaged_profiles
    return packaged_profiles()


def test_packaged_complete_immutable_and_round_trip(tmp_path):
    from uniti.app.theme_profiles import BUILTIN_IDS, ThemeProfileStore, COLOR_ROLES
    packaged = {p.id: p for p in profiles()}
    paper, slate = packaged['Paper'], packaged['Slate']
    assert paper.colors['editor.base'] == '#fbf7ef'
    assert slate.colors['editor.base'] == '#202830'
    non_native_ids = {i for i in BUILTIN_IDS if i not in ('System', 'Light', 'Dark')}
    assert set(packaged) == non_native_ids
    for profile in packaged.values():
        assert set(profile.colors) == set(COLOR_ROLES)
    with pytest.raises(TypeError):
        paper.colors['editor.base'] = '#ffffff'
    custom = replace(paper, id='custom-one', name='My paper')
    store = ThemeProfileStore(tmp_path / 'themes.json')
    store.save((custom,), custom.id)
    loaded = store.load('Dark')
    assert loaded.profiles == (custom,)
    assert loaded.active_id == custom.id


def test_schema_1_profile_migrates_by_freezing_todays_syntax_colors(tmp_path):
    """BF-063: a file written before syntax colors existed must not be
    dropped just because it predates `syntax.*` roles entirely.
    """
    from uniti.app.theme_profiles import ThemeProfileStore, THEME_SCHEMA

    paper = profiles()[0]
    legacy_colors = {k: v for k, v in paper.colors.items() if not k.startswith('syntax.')}
    payload = {
        'schema': 1,
        'profiles': [{'id': 'legacy-one', 'name': 'Legacy', 'base_mode': 'Light', 'colors': legacy_colors}],
        'active_id': 'legacy-one',
    }
    store = ThemeProfileStore(tmp_path / 'themes.json')
    store.path.write_text(json.dumps(payload))

    loaded = store.load('Light')

    assert not loaded.error
    migrated = loaded.profiles[0]
    assert all(migrated.colors[role] == paper.colors[role]
               for role in paper.colors if role.startswith('syntax.'))
    store.save(loaded.profiles, loaded.active_id)
    assert json.loads(store.path.read_text())['schema'] == THEME_SCHEMA == 2


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(extra=True),
    lambda p: p.update(base_mode='System'),
    lambda p: p.update(id='Paper'),
    lambda p: p.update(name='x' * 65),
    lambda p: p['colors'].update({'editor.base': 'red'}),
    lambda p: p['colors'].update({'unsupported': '#ffffff'}),
    lambda p: p['colors'].pop('editor.text'),
    lambda p: p['colors'].pop('syntax.keyword'),
])
def test_profile_validation(mutation):
    from uniti.app.theme_profiles import ThemeProfile
    data = profiles()[0].as_dict()
    data['id'] = 'custom-one'
    mutation(data)
    with pytest.raises(ValueError):
        ThemeProfile.from_dict(data)


def test_store_recovery_does_not_overwrite_damage(tmp_path):
    from uniti.app.theme_profiles import ThemeProfileStore
    path = tmp_path / 'themes.json'
    original = b'{"schema": 99, "profiles": []}'
    path.write_bytes(original)
    loaded = ThemeProfileStore(path).load('Dark')
    assert loaded.active_id == 'Dark'
    assert loaded.error
    assert path.read_bytes() == original


def test_unknown_active_falls_back_and_missing_migrates(tmp_path):
    from uniti.app.theme_profiles import ThemeProfileStore
    store = ThemeProfileStore(tmp_path / 'themes.json')
    assert store.load('Light').active_id == 'Light'
    store.path.write_text(json.dumps({'schema': 1, 'profiles': [], 'active_id': 'missing'}))
    assert store.load('Dark').active_id == 'Dark'


def test_atomic_failure_retains_both_profile_and_active(tmp_path, monkeypatch):
    from uniti.app import theme_profiles
    store = theme_profiles.ThemeProfileStore(tmp_path / 'themes.json')
    custom = replace(profiles()[0], id='custom-one', name='Mine')
    store.save((custom,), custom.id)
    before = store.path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(theme_profiles, 'atomic_write_json', fail)
    with pytest.raises(OSError, match='disk full'):
        store.save((), 'Slate')
    assert store.path.read_bytes() == before


def test_bounds_and_duplicate_profiles(tmp_path):
    from uniti.app.theme_profiles import ThemeProfileStore
    store = ThemeProfileStore(tmp_path / 'themes.json')
    paper = profiles()[0]
    with pytest.raises(ValueError):
        store.save(tuple(replace(paper, id=f'custom-{n}') for n in range(33)), 'Paper')
    custom = replace(paper, id='custom-one')
    with pytest.raises(ValueError):
        store.save((custom, custom), 'Paper')
    store.path.write_bytes(b' ' * (128 * 1024 + 1))
    assert store.load().error


@pytest.mark.parametrize('raw', [
    b'{"schema":1,"schema":1,"profiles":[],"active_id":"System"}',
    b'[' * 10000 + b']' * 10000,
], ids=['duplicate-key', 'excessive-nesting'])
def test_malformed_structure_recovers_without_exception_or_rewrite(tmp_path, raw):
    from uniti.app.theme_profiles import ThemeProfileStore
    store = ThemeProfileStore(tmp_path / 'themes.json')
    store.path.write_bytes(raw)
    assert store.load('Light').active_id == 'Light'
    assert store.load('Light').error
    assert store.path.read_bytes() == raw


def test_atomic_replace_failure_preserves_real_file_and_cleans_temp(tmp_path, monkeypatch):
    from uniti.app.theme_profiles import ThemeProfileStore
    from uniti.core.durability import NativeDurabilityAdapter
    store = ThemeProfileStore(tmp_path / 'themes.json')
    custom = replace(profiles()[0], id='custom-one', name='Mine')
    store.save((custom,), custom.id)
    original = store.path.read_bytes()
    def fail(self, source, target):
        raise OSError('replace failed')
    monkeypatch.setattr(NativeDurabilityAdapter, 'replace', fail)
    with pytest.raises(OSError):
        store.save((), 'Slate')
    assert store.path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [store.path]
