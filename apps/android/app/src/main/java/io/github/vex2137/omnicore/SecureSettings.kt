package io.github.vex2137.omnicore

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** API token is AES-GCM ciphertext. Its non-exportable key stays in Android Keystore. */
class SecureSettings(context: Context) : ClientSettings {
    private val preferences = context.getSharedPreferences("omnicore", Context.MODE_PRIVATE)
    private val alias = "omnicore.api.token.v1"
    override var url: String
        get() = preferences.getString("url", "") ?: ""
        set(value) {
            preferences.edit().putString("url", value).apply()
        }

    override var trustedLan: Boolean
        get() = preferences.getBoolean("trusted_lan", false)
        set(value) {
            preferences.edit().putBoolean("trusted_lan", value).apply()
        }

    override var theme: String
        get() = preferences.getString("theme", "system") ?: "system"
        set(value) {
            preferences.edit().putString("theme", value).apply()
        }

    override var language: String
        get() {
            preferences.getString("language", null)?.let {
                if (it in setOf("pl-PL", "en-US")) return it
            }
            val detected =
                initialLanguage(
                    android.content.res.Resources.getSystem()
                        .configuration
                        .locales
                        .toLanguageTags()
                        .split(',')
                )
            preferences.edit().putString("language", detected).apply()
            return detected
        }
        set(value) {
            preferences.edit().putString("language", value).apply()
        }

    override var conversationId: String?
        get() = preferences.getString("conversation", null)
        set(value) {
            preferences.edit().putString("conversation", value).apply()
        }

    override var generationId: String?
        get() = preferences.getString("generation", null)
        set(value) {
            preferences.edit().putString("generation", value).apply()
        }

    override var parameters: Parameters
        get() =
            try {
                WireJson.decodeFromString<Parameters>(
                    preferences.getString("parameters", "{}") ?: "{}"
                )
            } catch (_: Exception) {
                Parameters()
            }
        set(value) {
            preferences
                .edit()
                .putString("parameters", WireJson.encodeToString(Parameters.serializer(), value))
                .apply()
        }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let {
            return it
        }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            .apply {
                init(
                    KeyGenParameterSpec.Builder(
                            alias,
                            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                        )
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .setRandomizedEncryptionRequired(true)
                        .build()
                )
            }
            .generateKey()
    }

    private fun encrypted(value: String): Pair<String, String> {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        return Base64.encodeToString(cipher.doFinal(value.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP) to
            Base64.encodeToString(cipher.iv, Base64.NO_WRAP)
    }

    private fun readSecret(prefix: String): String? {
        val value = preferences.getString(prefix + "_cipher", null) ?: return null
        val iv = preferences.getString(prefix + "_iv", null) ?: throw ApiFailure("token_unavailable")
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
                init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)))
            }
            String(cipher.doFinal(Base64.decode(value, Base64.NO_WRAP)), Charsets.UTF_8)
        } catch (_: Exception) { throw ApiFailure("token_unavailable") }
    }

    private fun writeSecret(editor: android.content.SharedPreferences.Editor, prefix: String, value: String?) {
        if (value.isNullOrEmpty()) {
            editor.remove(prefix + "_cipher").remove(prefix + "_iv")
        } else {
            val encrypted = encrypted(value)
            editor.putString(prefix + "_cipher", encrypted.first).putString(prefix + "_iv", encrypted.second)
        }
    }

    override fun storeToken(token: String) {
        val editor = preferences.edit()
        writeSecret(editor, "token", token)
        if (!editor.commit()) throw ApiFailure("token_unavailable")
    }

    override fun readToken(): String = readSecret("token") ?: ""
    override fun readPendingPairing(): String? = readSecret("pairing")
    override fun hasPendingPairing() = preferences.contains("pairing_cipher")
    override fun storePendingPairing(value: String?) {
        val editor = preferences.edit()
        writeSecret(editor, "pairing", value)
        if (!editor.commit()) throw ApiFailure("token_unavailable")
    }

    override fun commitConnection(newUrl: String, newToken: String?, trusted: Boolean) {
        val editor = preferences.edit().putString("url", newUrl).putBoolean("trusted_lan", trusted)
        if (newToken != null) writeSecret(editor, "token", newToken)
        if (!editor.commit()) throw ApiFailure("token_unavailable")
    }
}
