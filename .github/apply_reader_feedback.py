from pathlib import Path

app = Path('app.py')
text = app.read_text()
marker = '@app.route("/contact", methods=["GET", "POST"])\n'
route = '''@app.route("/kwsnyderwriting/novel/<int:book_id>/chapter/<int:chapter_id>/feedback", methods=["POST"])
@member_required
def submit_reader_feedback(book_id, chapter_id):
    feedback = request.form.get("feedback", "").strip()
    if not feedback:
        return redirect(url_for("view_chapter", book_id=book_id, chapter_id=chapter_id, feedback_error="Please enter your feedback before submitting."))
    if len(feedback) > 20000:
        return redirect(url_for("view_chapter", book_id=book_id, chapter_id=chapter_id, feedback_error="Please keep feedback under 20,000 characters."))

    member_id = session.get("member_id")
    conn = get_db()
    chapter = conn.execute("SELECT id, book_id, chapter_number, title FROM manuscript_chapters WHERE id = ? AND book_id = ? AND published = 1", (chapter_id, book_id)).fetchone()
    book = conn.execute("SELECT id, title FROM manuscript_books WHERE id = ?", (book_id,)).fetchone()
    member = conn.execute("SELECT email FROM members WHERE id = ?", (member_id,)).fetchone()
    if not chapter or not book or not member:
        conn.close()
        abort(404)

    subject = f"Reader Feedback — {book['title']} — Chapter {chapter['chapter_number']}: {chapter['title']}"
    conn.execute(
        "INSERT INTO inbox_messages(message_type, name, email, subject, message, post_id, book_id, chapter_id, member_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("reader_feedback", "Subscriber Reader", member["email"], subject, feedback, None, book_id, chapter_id, member_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("view_chapter", book_id=book_id, chapter_id=chapter_id, feedback_sent="1"))


'''
if 'def submit_reader_feedback' not in text:
    if marker not in text:
        raise SystemExit('Contact route marker not found')
    app.write_text(text.replace(marker, route + marker, 1))

chapter = Path('templates/blog_templates/chapter.html')
c = chapter.read_text()
marker = '  <div class="actions" style="justify-content:space-between;margin-top:30px;">'
feedback = '''  {% if request.args.get('feedback_sent') == '1' %}
    <div style="margin-top:30px;padding:15px;border:1px solid #C9B78F;border-radius:8px;background:#F7F1E6;">
      <strong>Thank you.</strong> Your reader feedback has been sent to the author.
    </div>
  {% endif %}
  {% if request.args.get('feedback_error') %}
    <div style="margin-top:30px;padding:15px;border:1px solid #C9B78F;border-radius:8px;background:#F7F1E6;">
      {{ request.args.get('feedback_error') }}
    </div>
  {% endif %}

  <section style="margin-top:35px;padding-top:25px;border-top:1px solid #C9B78F;">
    <h2>Reader Feedback</h2>
    <p>If you're reading this chapter as a subscriber and would like to share your thoughts, send your feedback directly to the author.</p>
    <form method="post" action="{{ url_for('submit_reader_feedback', book_id=book['id'], chapter_id=chapter['id']) }}">
      <label for="reader-feedback">Your feedback</label>
      <textarea id="reader-feedback" name="feedback" rows="8" maxlength="20000" required style="width:100%;box-sizing:border-box;margin-top:8px;padding:12px;border:1px solid #C9B78F;border-radius:6px;font:inherit;resize:vertical;" placeholder="What did you think of this chapter?"></textarea>
      <button type="submit" style="margin-top:12px;padding:10px 16px;border:1px solid #C9B78F;border-radius:6px;background:#FFFDF8;cursor:pointer;font:inherit;">Send Feedback</button>
    </form>
  </section>

'''
if 'id="reader-feedback"' not in c:
    if marker not in c:
        raise SystemExit('Chapter actions marker not found')
    chapter.write_text(c.replace(marker, feedback + marker, 1))
