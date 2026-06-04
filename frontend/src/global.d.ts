// Allow importing CSS files without TypeScript errors
declare module '*.css' {
  const content: string;
  export default content;
}
