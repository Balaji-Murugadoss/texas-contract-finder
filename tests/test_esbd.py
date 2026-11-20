"""ESBD file-drop loader tests. tmp_path is a pytest fixture: a fresh empty folder for each test."""
import db
import esbd

HEADER = ("Name,Solicitation ID,Due Date,Due Time,Agency/Texas SmartBuy Member Number,Status,"
          "Posting Date,Created,Last Modified,NIGP Codes\n")


def test_esbd_keeps_newest_version_and_balances(tmp_path):
    (tmp_path / "export.csv").write_text(
        HEADER
        + "Old title,808-1,12/1/2026,2:00 PM,808,Posted,11/10/2026,11/10/2026 3:51 pm,"
          "11/10/2026 3:51 pm,90930-Building Construction;\n"
        + "New title,808-1,12/1/2026,2:00 PM,808,Addendum Posted,11/10/2026,11/10/2026 3:51 pm,"
          '11/20/2026 11:39 am,"90930-Building Construction;\n91039-Air Conditioning;"\n'
        + ",,,,,,,,,\n")
    con = db.connect(path=":memory:")
    s = esbd.load_drop(con, tmp_path)
    assert (s["rows_read"], s["loaded"], s["duplicates"], s["skipped_no_id"]) == (3, 1, 1, 1)
    title, deadline = con.execute("SELECT title, response_deadline FROM opportunities").fetchone()
    assert title == "New title" and deadline.hour == 14          # newest version wins; 2:00 PM -> 14:00
    esbd.load_drop(con, tmp_path)                                 # run twice: must not duplicate
    codes = con.execute("SELECT code FROM opportunity_codes ORDER BY code").fetchall()
    assert codes == [("90930",), ("91039",)]                      # the line break inside quotes stayed one row


def test_esbd_rejects_changed_format(tmp_path):
    (tmp_path / "renamed.csv").write_text("Title,ID\nx,1\n")
    s = esbd.load_drop(db.connect(path=":memory:"), tmp_path)
    assert s["bad_files"] == ["renamed.csv"] and s["loaded"] == 0
