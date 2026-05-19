"""
Тексты интерфейса и сообщений бота (константы строк).
"""
from app.constants import texts


def translate(variable_name: str, *args) -> str:
    """
    Возвращает форматированную строку по имени константы из texts.

    :param variable_name: имя переменной в app.constants.texts.
    :param args: аргументы для str.format.
    """
    if not hasattr(texts, variable_name):
        return variable_name
    text = getattr(texts, variable_name)

    args = list(args)
    placeholders = text.count("{}")
    if len(args) < placeholders:
        args.extend(["{}"] * (placeholders - len(args)))
    return text.format(*args)


_ = translate
