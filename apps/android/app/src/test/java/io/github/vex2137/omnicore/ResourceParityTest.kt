package io.github.vex2137.omnicore

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.*
import org.junit.Test

class ResourceParityTest {
    @Test
    fun polishAndEnglishHaveMatchingKeysAndFormatArguments() {
        fun catalog(folder: String): Map<String, String> {
            val parser = DocumentBuilderFactory.newInstance()
            parser.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
            val nodes =
                parser
                    .newDocumentBuilder()
                    .parse(File("src/main/res/$folder/strings.xml"))
                    .getElementsByTagName("string")
            return (0 until nodes.length).associate { index ->
                val node = nodes.item(index)
                node.attributes.getNamedItem("name").nodeValue to node.textContent
            }
        }
        val en = catalog("values")
        val pl = catalog("values-pl")
        assertEquals(en.keys, pl.keys)
        val formats = Regex("%[0-9]+[$][a-z]")
        en.forEach { (key, value) ->
            assertTrue(key, value.isNotBlank() && pl.getValue(key).isNotBlank())
            assertEquals(
                key,
                formats.findAll(value).map { it.value }.toList(),
                formats.findAll(pl.getValue(key)).map { it.value }.toList(),
            )
        }
    }
}
