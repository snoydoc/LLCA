import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import { CodeBlock } from './CodeBlock';

interface Props {
  content:     string;
  isStreaming?: boolean;
}

// Schema sanitize étendu pour autoriser les classes highlight.js
const sanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code:  [...(defaultSchema.attributes?.code  ?? []), ['className', /^language-/]],
    span:  [...(defaultSchema.attributes?.span  ?? []), ['className', /^hljs/]],
    div:   [...(defaultSchema.attributes?.div   ?? []), ['className', /^hljs/]],
  },
};

export function MarkdownRenderer({ content, isStreaming }: Props) {
  return (
    <div className={`markdown-body ${isStreaming ? 'is-streaming' : ''}`}>
      <ReactMarkdown
        rehypePlugins={[
          [rehypeSanitize, sanitizeSchema],
          rehypeHighlight,
        ]}
        components={{
          // Downgrade H1→H3, H2→H4 dans les bulles
          h1: ({ children }) => <h3 className="md-h1">{children}</h3>,
          h2: ({ children }) => <h4 className="md-h2">{children}</h4>,

          // CodeBlock dédié pour les blocs fenced
          code({ className, children, ...props }: any) {
            // Normaliser children en string safe — react-markdown peut passer
            // un Array de ReactElements pour les spans inline complexes,
            // ce qui donne [object Object] si on fait String(array).
            const childText = Array.isArray(children)
              ? children.map((c: any) =>
                  typeof c === 'string' ? c
                  : typeof c?.props?.children === 'string' ? c.props.children
                  : '')
                .join('')
              : typeof children === 'string' ? children
              : String(children ?? '');

            const isInline = !className && !childText.includes('\n');
            const lang = /language-(\w+)/.exec(className ?? '')?.[1] ?? '';
            if (isInline) {
              return <code className="inline-code" {...props}>{children}</code>;
            }
            return (
              <CodeBlock
                language={lang}
                code={childText.replace(/\n$/, '')}
              />
            );
          },

          // Blockquote → info-box
          blockquote: ({ children }) => (
            <div className="blockquote-info">{children}</div>
          ),

          // Table avec wrapper scrollable
          table: ({ children }) => (
            <div className="table-wrapper"><table>{children}</table></div>
          ),

          // Liens : ouvrir dans le navigateur externe
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              onClick={e => { e.preventDefault(); /* UI-04 : shell.openExternal */ }}
            >
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
