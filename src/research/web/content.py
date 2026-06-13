def wrap_untrusted_source(content: str) -> str:
    return f"<untrusted_source>\n{content}\n</untrusted_source>"
