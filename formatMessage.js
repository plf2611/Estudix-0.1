// Função aprimorada para formatar mensagens com markdown
function formatMessage(message) {
    if (!message) return '';
    
    // Processar tabelas antes de quebras de linha
    // Formato: | Coluna 1 | Coluna 2 | Coluna 3 |
    //          |----------|----------|----------|
    //          | Dado 1   | Dado 2   | Dado 3   |
    let formattedMsg = message;
    
    // Identificar tabelas
    const tableRegex = /(\|[^\n]+\|\s*\n\|[-:|]+\|[^\n]+\|\s*(?:\n\|[^\n]+\|\s*)*)/g;
    formattedMsg = formattedMsg.replace(tableRegex, function(table) {
        // Processar linhas da tabela
        const rows = table.split('\n').filter(row => row.trim().length > 0);
        
        // Construir tabela HTML
        let htmlTable = '<table class="table table-bordered table-dark table-sm"><thead>';
        
        // Cabeçalho da tabela
        const headerMatch = rows[0].match(/\|([^|]*)/g);
        if (headerMatch) {
            htmlTable += '<tr>';
            headerMatch.forEach((column, index) => {
                if (index === 0 && column.trim() === '|') return; // Pular primeira célula vazia
                const cellContent = column.replace('|', '').trim();
                htmlTable += `<th>${cellContent}</th>`;
            });
            htmlTable += '</tr>';
        }
        
        htmlTable += '</thead><tbody>';
        
        // Ignorar a linha de separação (segunda linha)
        
        // Dados da tabela (a partir da terceira linha)
        for (let i = 2; i < rows.length; i++) {
            const rowMatch = rows[i].match(/\|([^|]*)/g);
            if (rowMatch) {
                htmlTable += '<tr>';
                rowMatch.forEach((column, index) => {
                    if (index === 0 && column.trim() === '|') return; // Pular primeira célula vazia
                    const cellContent = column.replace('|', '').trim();
                    htmlTable += `<td>${cellContent}</td>`;
                });
                htmlTable += '</tr>';
            }
        }
        
        htmlTable += '</tbody></table>';
        return htmlTable;
    });
    
    // Processar os blocos de código
    formattedMsg = formattedMsg.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
    
    // Processar código inline
    formattedMsg = formattedMsg.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Substituir negrito (** **) por HTML
    formattedMsg = formattedMsg.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    
    // Substituir itálico (* *) por HTML - evitar processar asteriscos dentro de HTML já criado
    formattedMsg = formattedMsg.replace(/(?<!<[^>]*)\*(.*?)\*(?![^<]*>)/g, '<em>$1</em>');
    
    // Identificar listas (vazias ou não) e convertê-las para HTML
    // Vamos tratar blocos de listas primeiro
    const listRegex = /((?:^\s*[-*]\s+.+\n?)+)/gm;
    formattedMsg = formattedMsg.replace(listRegex, function(listBlock) {
        // Converter cada item da lista
        let htmlList = '<ul>';
        const items = listBlock.match(/^\s*[-*]\s+(.+)$/gm);
        
        if (items) {
            items.forEach(item => {
                const content = item.replace(/^\s*[-*]\s+/, '').trim();
                htmlList += `<li>${content}</li>`;
            });
        }
        
        htmlList += '</ul>';
        return htmlList;
    });
    
    // Identificar listas numeradas
    const orderedListRegex = /((?:^\s*\d+\.\s+.+\n?)+)/gm;
    formattedMsg = formattedMsg.replace(orderedListRegex, function(listBlock) {
        // Converter cada item da lista numerada
        let htmlList = '<ol>';
        const items = listBlock.match(/^\s*\d+\.\s+(.+)$/gm);
        
        if (items) {
            items.forEach(item => {
                const content = item.replace(/^\s*\d+\.\s+/, '').trim();
                htmlList += `<li>${content}</li>`;
            });
        }
        
        htmlList += '</ol>';
        return htmlList;
    });
    
    // Tratar parágrafos vazios como quebras de parágrafo
    formattedMsg = formattedMsg.replace(/\n\s*\n/g, '</p><p>');
    
    // Substituir quebras de linha simples por <br>
    formattedMsg = formattedMsg.replace(/\n/g, '<br>');
    
    // Se o conteúdo não começar com uma tag HTML, envolva-o em <p>
    if (!formattedMsg.startsWith('<')) {
        formattedMsg = '<p>' + formattedMsg + '</p>';
    }
    
    return formattedMsg;
}
