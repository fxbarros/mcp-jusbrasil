"""Script interativo para salvar credenciais do JusBrasil no Keychain.

Rode UMA VEZ:
    uv run python setup_credenciais.py

Nunca edite este arquivo para colar credenciais dentro —
responda interativamente quando ele pedir.
"""
import getpass
import keyring

SERVICO = "mcp-jusbrasil"

email = input("E-mail JusBrasil: ").strip()
senha = getpass.getpass("Senha JusBrasil (nao aparece na tela): ")

keyring.set_password(SERVICO, "email", email)
keyring.set_password(SERVICO, "senha", senha)

print()
print(f"[OK] Credenciais salvas no Keychain sob o servico '{SERVICO}'.")
print("    - email:", email)
print("    - senha: (oculta)")
