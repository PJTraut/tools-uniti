from __future__ import annotations

from pathlib import Path

from uniti.core.environments.sfm.paratext_project import (
    PARATEXT_BOOKS,
    BookNaming,
    ParatextProject,
    book_file_number,
    project_for_file,
)

BOM = chr(0xFEFF)


def _present(*codes: str) -> str:
    return "".join("1" if code in codes else "0" for code in PARATEXT_BOOKS)


def _settings(folder: Path, *, naming: str, extra: str = "", present: str | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    books = "" if present is None else f"<BooksPresent>{present}</BooksPresent>"
    (folder / "Settings.xml").write_text(
        "<ScriptureText>"
        "<Name>NIV11</Name><FullName>New International Version</FullName>"
        "<LanguageIsoCode>en:::</LanguageIsoCode><Encoding>65001</Encoding>"
        "<Versification>4</Versification><StyleSheet>usfm.sty</StyleSheet>"
        "<Guid>abc123</Guid>"
        f"{naming}{books}{extra}</ScriptureText>",
        encoding="utf-8",
    )


def _book(folder: Path, name: str, code: str) -> Path:
    path = folder / name
    path.write_text(f"\\id {code}\n\\c 1\n\\p\n\\v 1 Text.\n", encoding="utf-8")
    return path


def test_book_file_numbers_follow_paratext():
    assert book_file_number("GEN") == "01"
    assert book_file_number("MAL") == "39"
    assert book_file_number("MAT") == "41"  # 40 is skipped
    assert book_file_number("REV") == "67"
    assert book_file_number("TOB") == "68"
    assert book_file_number("FRT") == "A0"
    assert book_file_number("INT") == "A7"
    assert book_file_number("TDX") == "B0"
    assert book_file_number("ZZZ") is None


def test_naming_forms():
    assert BookNaming("", "NIV11.SFM", "41MAT").file_name("MAT") == "41MATNIV11.SFM"
    assert BookNaming("x", ".usfm", "MAT").file_name("GEN") == "xGEN.usfm"
    assert BookNaming("", ".SFM", "41").file_name("REV") == "67.SFM"
    assert BookNaming("", ".SFM", "MAT41").file_name("GEN") == "GEN01.SFM"


def test_load_reads_the_project_settings(tmp_path: Path):
    _settings(
        tmp_path,
        naming='<Naming PrePart="" PostPart="NIV11.SFM" BookNameForm="41MAT" />',
        present=_present("GEN", "MAT"),
    )
    project = ParatextProject.load(tmp_path)

    assert project is not None
    assert (project.name, project.full_name, project.language) == ("NIV11", "New International Version", "en")
    assert project.encoding == "utf-8"
    assert (project.versification_name, project.versification_file) == ("English", "eng")
    assert project.stylesheet == "usfm.sty" and project.guid == "abc123"
    assert project.books_present == ("GEN", "MAT")
    assert project.book_path("mat") == tmp_path / "41MATNIV11.SFM"


def test_older_file_name_elements_are_read(tmp_path: Path):
    _settings(
        tmp_path,
        naming="<FileNamePrePart>p</FileNamePrePart><FileNamePostPart>.ptx</FileNamePostPart>"
        "<FileNameBookNameForm>MAT</FileNameBookNameForm>",
    )
    project = ParatextProject.load(tmp_path)
    assert project.naming == BookNaming("p", ".ptx", "MAT")


def test_books_are_present_existing_files_in_canon_order(tmp_path: Path):
    _settings(
        tmp_path,
        naming='<Naming PrePart="" PostPart="NIV11.SFM" BookNameForm="41MAT" />',
        present=_present("GEN", "EXO", "MAT", "TOB", "FRT"),
    )
    _book(tmp_path, "41MATNIV11.SFM", "MAT")
    _book(tmp_path, "01GENNIV11.SFM", "GEN")
    _book(tmp_path, "A0FRTNIV11.SFM", "FRT")
    _book(tmp_path, "68TOBNIV11.SFM", "TOB")
    # EXO is listed but its file is missing; LEV exists but isn't listed.
    _book(tmp_path, "03LEVNIV11.SFM", "LEV")

    books = ParatextProject.load(tmp_path).books()

    assert [book.code for book in books] == ["GEN", "MAT", "TOB", "FRT"]
    assert books[0].path == tmp_path / "01GENNIV11.SFM"


def test_a_misnamed_book_is_found_by_its_id(tmp_path: Path):
    _settings(
        tmp_path,
        naming='<Naming PrePart="" PostPart="NIV11.SFM" BookNameForm="41MAT" />',
        present=_present("GEN", "PS2"),
    )
    path = tmp_path / "99PS2NIV11.SFM"
    path.write_text(BOM + "\\id PS2\n\\c 1\n", encoding="utf-8")
    _book(tmp_path, "01GENNIV11.SFM", "GEN")

    books = ParatextProject.load(tmp_path).books()

    assert [(book.code, book.path.name) for book in books] == [
        ("GEN", "01GENNIV11.SFM"),
        ("PS2", "99PS2NIV11.SFM"),
    ]


def test_without_books_present_every_existing_book_counts(tmp_path: Path):
    _settings(tmp_path, naming='<Naming PrePart="" PostPart=".usfm" BookNameForm="MAT" />')
    _book(tmp_path, "REV.usfm", "REV")
    _book(tmp_path, "GEN.usfm", "GEN")
    assert [book.code for book in ParatextProject.load(tmp_path).books()] == ["GEN", "REV"]


def test_book_names_come_from_book_names_xml(tmp_path: Path):
    _settings(tmp_path, naming='<Naming PrePart="" PostPart=".SFM" BookNameForm="MAT" />')
    _book(tmp_path, "GEN.SFM", "GEN")
    (tmp_path / "BookNames.xml").write_text(
        '<BookNames><book code="GEN" abbr="Gen" short="Genesis" long="The Book of Genesis" /></BookNames>',
        encoding="utf-8",
    )
    project = ParatextProject.load(tmp_path)
    assert project.books()[0].name == "Genesis"
    assert project.book_for("gen").code == "GEN"
    assert project.book_for("EXO") is None


def test_folders_without_a_valid_settings_file_are_not_projects(tmp_path: Path):
    assert ParatextProject.load(tmp_path) is None
    (tmp_path / "Settings.xml").write_text("<ScriptureText><Name>", encoding="utf-8")
    assert ParatextProject.load(tmp_path) is None
    (tmp_path / "Settings.xml").write_text("<Other><Name>X</Name></Other>", encoding="utf-8")
    assert ParatextProject.load(tmp_path) is None
    (tmp_path / "Settings.xml").write_text("<ScriptureText><FullName>No short name</FullName></ScriptureText>")
    assert ParatextProject.load(tmp_path) is None
    (tmp_path / "Settings.xml").write_bytes(b"<ScriptureText>" + b" " * (1024 * 1024) + b"</ScriptureText>")
    assert ParatextProject.load(tmp_path) is None


def test_unknown_versification_and_encoding_fall_back(tmp_path: Path):
    folder = tmp_path / "odd"
    folder.mkdir()
    (folder / "Settings.xml").write_text(
        "<ScriptureText><Name>ODD</Name><Versification>9</Versification><Encoding>437</Encoding></ScriptureText>",
        encoding="utf-8",
    )
    project = ParatextProject.load(folder)
    assert project.versification_name == "English"
    assert project.encoding is None
    assert project.naming == BookNaming()


def test_project_for_file_finds_the_folder_project_and_rereads_changes(tmp_path: Path):
    _settings(tmp_path, naming='<Naming PrePart="" PostPart=".SFM" BookNameForm="MAT" />')
    book = _book(tmp_path, "GEN.SFM", "GEN")
    loose = tmp_path / "loose"
    loose.mkdir()
    single = _book(loose, "GEN.usfm", "GEN")

    project = project_for_file(book)
    assert project is not None and project.name == "NIV11" and project.owns(book)
    assert project_for_file(single) is None
    assert not project.owns(single)

    import os

    settings = tmp_path / "Settings.xml"
    settings.write_text(settings.read_text().replace("NIV11", "NIV84"), encoding="utf-8")
    stat = settings.stat()
    os.utime(settings, (stat.st_atime, stat.st_mtime + 5))
    assert project_for_file(book).name == "NIV84"


def test_the_named_stylesheet_replaces_usfm_sty(tmp_path: Path):
    from uniti.core.environments.sfm.style_layers import (
        PROJECT_STYLESHEET_CANDIDATES,
        discover_project_stylesheets,
        project_stylesheet_candidates,
    )

    _settings(tmp_path, naming='<Naming PrePart="" PostPart=".SFM" BookNameForm="MAT" />', extra="")
    settings = tmp_path / "Settings.xml"
    settings.write_text(settings.read_text().replace("usfm.sty", "usfm_sb.sty"), encoding="utf-8")
    book = _book(tmp_path, "GEN.SFM", "GEN")
    (tmp_path / "usfm.sty").write_text("\\Marker p\n\\FontSize 10\n", encoding="utf-8")
    (tmp_path / "usfm_sb.sty").write_text("\\Marker p\n\\FontSize 11\n", encoding="utf-8")

    candidates = [relative for relative, _origin in project_stylesheet_candidates(book)]
    assert candidates[0] == "usfm_sb.sty" and "usfm.sty" not in candidates
    assert [layer.name for layer in discover_project_stylesheets(book)] == ["usfm_sb.sty"]

    loose = tmp_path / "loose"
    loose.mkdir()
    assert project_stylesheet_candidates(_book(loose, "GEN.usfm", "GEN")) == PROJECT_STYLESHEET_CANDIDATES


def test_a_stylesheet_name_with_a_path_is_ignored(tmp_path: Path):
    from uniti.core.environments.sfm.style_layers import PROJECT_STYLESHEET_CANDIDATES, project_stylesheet_candidates

    _settings(tmp_path, naming='<Naming PrePart="" PostPart=".SFM" BookNameForm="MAT" />')
    settings = tmp_path / "Settings.xml"
    settings.write_text(settings.read_text().replace("usfm.sty", "../outside.sty"), encoding="utf-8")
    assert project_stylesheet_candidates(_book(tmp_path, "GEN.SFM", "GEN")) == PROJECT_STYLESHEET_CANDIDATES


def test_project_books_open_in_the_declared_encoding(tmp_path: Path):
    from uniti.core.environments.sfm.paratext_project import project_encoding_profile

    legacy = tmp_path / "legacy"
    _settings(legacy, naming='<Naming PrePart="" PostPart=".SFM" BookNameForm="MAT" />')
    settings = legacy / "Settings.xml"
    settings.write_text(settings.read_text().replace("65001", "1252"), encoding="utf-8")
    book = legacy / "GEN.SFM"
    book.write_bytes("\\id GEN\n\\v 1 Café\n".encode("windows-1252"))
    assert project_encoding_profile(book).key == "windows-1252"

    modern = tmp_path / "modern"
    _settings(modern, naming='<Naming PrePart="" PostPart=".SFM" BookNameForm="MAT" />')
    with_bom = modern / "GEN.SFM"
    with_bom.write_bytes(b"\xef\xbb\xbf" + "\\id GEN\n\\v 1 Café\n".encode("utf-8"))
    assert project_encoding_profile(with_bom).bom == b"\xef\xbb\xbf"
    plain = modern / "EXO.SFM"
    plain.write_bytes("\\id EXO\n".encode("utf-8"))
    assert project_encoding_profile(plain).key == "utf-8"
    # Content that disagrees with the declaration: leave it to detection.
    broken = modern / "LEV.SFM"
    broken.write_bytes(b"\\id LEV\n\\v 1 Caf\xe9\n")
    assert project_encoding_profile(broken) is None

    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "GEN.usfm").write_text("\\id GEN\n", encoding="utf-8")
    assert project_encoding_profile(loose / "GEN.usfm") is None
