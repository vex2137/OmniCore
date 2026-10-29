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

    override fun storeToken(token: String) {
        if (token.isEmpty()) {
            preferences.edit().remove("token_cipher").remove("token_iv").apply()
            return
        }
        val cipher =
            Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val bytes = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
        preferences
            .edit()
            .putString("token_cipher", Base64.encodeToString(bytes, Base64.NO_WRAP))
            .putString("token_iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .apply()
    }

    override fun readToken(): String {
        val encrypted = preferences.getString("token_cipher", null) ?: return ""
        val iv = preferences.getString("token_iv", null) ?: throw ApiFailure("token_unavailable")
        return try {
            val cipher =
                Cipher.getInstance("AES/GCM/NoPadding").apply {
                    init(
                        Cipher.DECRYPT_MODE,
                        key(),
                        GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
                    )
                }
            String(cipher.doFinal(Base64.decode(encrypted, Base64.NO_WRAP)), Charsets.UTF_8)
        } catch (_: Exception) {
            throw ApiFailure("token_unavailable")
        }
    }
}
