/* Renders model text as safe HTML: markdown (marked), code highlighting (highlight.js) and math (KaTeX), sanitized by
DOMPurify. Used for every message bubble (ReplyBody.render) and the file viewer (chat_file_viewer.js). */
class MessageMarkdown {
  // $$...$$ and \[...\] (display math), \(...\) and $...$ (inline math). A single dollar follows Pandoc's rule so
  // prices stay prose ("$5 and $10"): the opening $ is followed by a non-space, the closing one follows a non-space and
  // isn't followed by a digit, and (checked in extractMath) the content looks like math. Extraction runs on the raw
  // model text before marked.parse, whose CommonMark backslash-escape rule would drop the delimiters' backslashes.
  static MATH_SPAN_RE =
    /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|(?<![\\$\w])\$(?=\S)([^$\n]+?)(?<=\S)\$(?![\d$])/g;
  // Inline $...$ only when it looks like math: a TeX command, sub/superscript, braces, an operator, or one letter.
  static DOLLAR_MATH_LOOK_RE = /[\\^_{}=+*\/<>]|^[A-Za-z]$/;
  // Code is never math: fenced blocks (also one still streaming in) and inline code spans are left as they are.
  static CODE_SEGMENT_RE = /(```[\s\S]*?(?:```|$)|`[^`\n]*`)/;

  /* Configures marked once, so all model output renders alike: GitHub-style line breaks and highlight.js for fenced
  code. Highlighting needs a custom `code` renderer: marked v5+ (this app uses v15) ignores the old `highlight` option. */
  static configure() {
    marked.use({
      renderer: {
        code({ text, lang }) {
          // Trust `lang` only if it is a real language name (it reaches an HTML class attribute) that highlight.js
          // knows; hljs.getLanguage is undefined for hints like a model-invented "pseudocode".
          const language = lang && /^[\w+-]+$/.test(lang) && hljs.getLanguage(lang) ? lang : null;
          const highlighted = language
            ? hljs.highlight(text, { language }).value
            : hljs.highlightAuto(text).value;
          const langClass = language ? ` language-${language}` : "";
          // Every vendored theme's CSS targets the "hljs" class (app/static/vendor/highlightjs/styles/*.css).
          return `<pre><code class="hljs${langClass}">${highlighted}</code></pre>`;
        },
      },
    });
    marked.setOptions({ breaks: true });
  }

  /* Plain letters/digits/"@", which marked and DOMPurify leave unchanged, swapped back for KaTeX's HTML in render. */
  static placeholder(index) {
    return `@@KATEX_MATH_${index}@@`;
  }

  /* Pulls math spans out of `text` before markdown parsing, renders each with KaTeX and leaves a placeholder. A span
  still streaming in (an opening \[ with no closing \]) stays plain text until it completes. */
  static extractMath(text) {
    const mathHtml = [];
    const replaceMath = (part) =>
      part.replace(MessageMarkdown.MATH_SPAN_RE, (match, dollarBlock, bracketBlock, parenInline, dollarInline) => {
        if (dollarInline !== undefined && !MessageMarkdown.DOLLAR_MATH_LOOK_RE.test(dollarInline)) return match;
        const displayMode = dollarBlock !== undefined || bracketBlock !== undefined;
        const tex = dollarBlock ?? bracketBlock ?? parenInline ?? dollarInline;
        let html;
        try {
          // throwOnError: false shows a parse error as red text, so a malformed \[...\] doesn't break the reply.
          html = katex.renderToString(tex, { throwOnError: false, displayMode });
        } catch (_err) {
          return match;
        }
        mathHtml.push(html);
        return MessageMarkdown.placeholder(mathHtml.length - 1);
      });
    // split with a capture group: odd entries are code segments, kept as they are.
    const placeholderText = text
      .split(MessageMarkdown.CODE_SEGMENT_RE)
      .map((part, i) => (i % 2 ? part : replaceMath(part)))
      .join("");
    return { placeholderText, mathHtml };
  }

  static render(container, text) {
    const { placeholderText, mathHtml } = MessageMarkdown.extractMath(text || "");
    let html = DOMPurify.sanitize(marked.parse(placeholderText));
    // After sanitizing: KaTeX's HTML is trusted (not raw model text) and has MathML tags DOMPurify would strip.
    mathHtml.forEach((rendered, index) => {
      html = html.split(MessageMarkdown.placeholder(index)).join(rendered);
    });
    container.innerHTML = html;
    ChatTables.frame(container);
    // Direction follows the current (maybe still streaming) text; see app.js detectTextDirection.
    container.dir = detectTextDirection(text || "");
  }
}

MessageMarkdown.configure();
